"""Apple Music song downloader using wrapper-manager for FairPlay decryption."""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import queue
from dataclasses import dataclass, field
from xml.etree import ElementTree

import grpc
import httpx
import m3u8
from mutagen.mp4 import MP4, MP4Cover

from proto import manager_pb2, manager_pb2_grpc

import socket
import struct

PREFETCH_KEY = "skd://itunes.apple.com/P000000000/s1/e1"
CODEC_KEY_SUFFIX = {"alac": "c23", "aac": "c22", "ec3": "c24", "ac3": "c24", "atmos": "c24"}
CODEC_REGEX = {
    "alac": r"audio-alac-stereo-\d{5,6}-\d{2}$",
    "aac": r"audio-stereo-\d{3}$",
    "atmos": r"audio-(atmos|ec3)-\d{4}$",
}
MAX_RETRIES = 3
REQUIRED_TOOLS = ["ffmpeg", "gpac", "MP4Box", "mp4edit", "mp4extract"]


def check_tools() -> list[str]:
    """Return list of missing external tools."""
    return [t for t in REQUIRED_TOOLS if not shutil.which(t)]


# --- TCP wrapper protocol ---

def pack_decrypt_setup(adam_id: str, uri: str) -> bytes:
    """Pack the decrypt setup message: uint8 adam_len + adam + uint8 uri_len + uri."""
    adam_bytes = adam_id.encode("ascii")
    uri_bytes = uri.encode("ascii")
    return (
        struct.pack("B", len(adam_bytes)) + adam_bytes
        + struct.pack("B", len(uri_bytes)) + uri_bytes
    )


def pack_sample(sample: bytes) -> bytes:
    """Pack a sample: uint32 big-endian size + raw bytes. Empty = terminator."""
    return struct.pack(">I", len(sample)) + sample


def readfull(stream, n: int) -> bytes:
    """Read exactly n bytes from a file-like object or socket."""
    buf = b""
    while len(buf) < n:
        if hasattr(stream, "recv"):
            chunk = stream.recv(n - len(buf))
        else:
            chunk = stream.read(n - len(buf))
        if not chunk:
            raise RuntimeError(f"Short read: got {len(buf)} bytes, expected {n}")
        buf += chunk
    return buf


@dataclass
class M3U8Info:
    uri: str
    keys: list[str]
    codec_id: str


@dataclass
class SampleInfo:
    desc_index: int
    data: bytes
    duration: int


@dataclass
class SongInfo:
    samples: list[SampleInfo]
    nhml: str
    decoder_params: bytes | None
    params: dict = field(default_factory=dict)


class WrapperManagerClient:
    """gRPC client for the wrapper-manager decryption service."""

    def __init__(self, url: str, secure: bool = True):
        if secure:
            self.channel = grpc.secure_channel(url, grpc.ssl_channel_credentials())
        else:
            self.channel = grpc.insecure_channel(url)
        self.stub = manager_pb2_grpc.WrapperManagerServiceStub(self.channel)

    def status(self) -> dict:
        from google.protobuf.empty_pb2 import Empty
        resp = self.stub.Status(Empty())
        return {
            "ready": resp.data.ready,
            "regions": list(resp.data.regions),
            "clients": resp.data.client_count,
        }

    def get_m3u8(self, adam_id: str) -> str:
        req = manager_pb2.M3U8Request(
            data=manager_pb2.M3U8DataRequest(adam_id=adam_id)
        )
        resp = self.stub.M3U8(req)
        if resp.header.code != 0:
            raise RuntimeError(f"M3U8 error: {resp.header.msg}")
        return resp.data.m3u8

    def _decrypt_batch(
        self, adam_id: str, keys: list[str], samples: list[tuple[int, SampleInfo]]
    ) -> dict[int, bytes]:
        """Send a batch of (index, sample) pairs for decryption. Returns {index: decrypted_bytes}."""
        results: dict[int, bytes] = {}
        req_queue: queue.Queue = queue.Queue()
        errors: list[str] = []

        def request_gen():
            while True:
                item = req_queue.get()
                if item is None:
                    return
                yield item

        def read_responses(resp_iter):
            try:
                for resp in resp_iter:
                    if resp.data.adam_id == "KEEPALIVE":
                        continue
                    if resp.header.code != 0:
                        errors.append(
                            f"Sample {resp.data.sample_index}: {resp.header.msg}"
                        )
                        continue
                    results[resp.data.sample_index] = resp.data.sample
            except grpc.RpcError as e:
                errors.append(str(e))

        resp_iter = self.stub.Decrypt(request_gen())
        reader = threading.Thread(target=read_responses, args=(resp_iter,))
        reader.start()

        for i, sample in samples:
            key_idx = min(sample.desc_index, len(keys) - 1)
            req = manager_pb2.DecryptRequest(
                data=manager_pb2.DecryptData(
                    adam_id=adam_id,
                    key=keys[key_idx],
                    sample_index=i,
                    sample=sample.data,
                )
            )
            req_queue.put(req)

        req_queue.put(None)
        reader.join()
        return results

    def decrypt_samples(
        self, adam_id: str, keys: list[str], samples: list[SampleInfo]
    ) -> list[bytes]:
        """Decrypt all samples via bidirectional gRPC stream with retries."""
        all_results: dict[int, bytes] = {}
        pending = list(enumerate(samples))

        for attempt in range(MAX_RETRIES):
            if not pending:
                break
            if attempt > 0:
                print(f"    retry {attempt}/{MAX_RETRIES - 1} for {len(pending)} samples...")

            batch_results = self._decrypt_batch(
                adam_id, keys, [(i, s) for i, s in pending]
            )
            all_results.update(batch_results)

            # Find what's still missing
            pending = [(i, s) for i, s in pending if i not in batch_results]

            if (attempt == 0) and not pending:
                break  # all good on first try

        if pending:
            missing_indices = [i for i, _ in pending]
            raise RuntimeError(
                f"Failed to decrypt {len(pending)} samples after {MAX_RETRIES} attempts: {missing_indices[:10]}..."
            )

        return [all_results[i] for i in range(len(samples))]

    def close(self):
        self.channel.close()


def parse_m3u8(m3u8_content: str, codec: str = "alac") -> M3U8Info:
    """Parse M3U8 master playlist to find the stream URI and key URIs."""
    # Handle URL vs raw content
    if m3u8_content.startswith("http"):
        resp = httpx.get(m3u8_content, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
        base_uri = m3u8_content
        m3u8_content = resp.text
    else:
        base_uri = None

    master = m3u8.loads(m3u8_content, uri=base_uri)
    regex = CODEC_REGEX.get(codec)
    if not regex:
        raise ValueError(f"Unsupported codec: {codec}. Supported: {list(CODEC_REGEX)}")

    # Find matching audio media entries
    matches = [
        m for m in master.media
        if m.group_id and re.match(regex, m.group_id)
    ]
    if not matches:
        available = sorted(set(m.group_id for m in master.media if m.group_id))
        raise RuntimeError(
            f"No {codec} stream found. Available: {available}"
        )

    best = matches[0]
    variant_url = best.absolute_uri or best.uri
    if not variant_url:
        raise RuntimeError(f"No URI for media entry {best.group_id}")

    # Fetch variant playlist
    resp = httpx.get(variant_url, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    variant = m3u8.loads(resp.text, uri=variant_url)

    # Get the fMP4 URI from segment map
    uri = None
    if variant.segment_map:
        sm = variant.segment_map[0]
        uri = sm.absolute_uri or sm.uri
    if not uri and variant.segments:
        uri = variant.segments[0].absolute_uri or variant.segments[0].uri
    if not uri:
        raise RuntimeError("No media URI found in variant M3U8")

    # Extract FairPlay key URIs
    key_suffix = CODEC_KEY_SUFFIX.get(codec, "c6")
    keys = [PREFETCH_KEY]
    for key in variant.keys:
        if key and key.uri and key.uri.startswith("skd://"):
            if key.uri.endswith(key_suffix):
                keys.append(key.uri)
    # Fallback: grab all skd:// keys if none matched the suffix
    if len(keys) == 1:
        for key in variant.keys:
            if key and key.uri and key.uri.startswith("skd://"):
                keys.append(key.uri)

    return M3U8Info(uri=uri, keys=keys, codec_id=best.group_id)


def download_encrypted(uri: str) -> bytes:
    """Download the encrypted fMP4 from Apple's CDN."""
    print(f"  downloading encrypted audio...")
    resp = httpx.get(uri, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()
    size_kb = len(resp.content) / 1024
    print(f"  downloaded {size_kb:.0f} KB")
    return resp.content


def _run(cmd: list[str], **kwargs):
    """Run a subprocess, raising on failure with stderr."""
    r = subprocess.run(cmd, capture_output=True, **kwargs)
    if r.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stderr: {r.stderr.decode(errors='replace')}"
        )
    return r


def extract_samples(encrypted: bytes, codec: str, tmpdir: str) -> SongInfo:
    """Extract encrypted samples from fMP4 for decryption."""
    raw_path = os.path.join(tmpdir, "raw.mp4")
    with open(raw_path, "wb") as f:
        f.write(encrypted)

    # 1. NHML extraction with gpac
    nhml_out = os.path.join(tmpdir, "raw.nhml")
    _run(["gpac", "-i", raw_path, "nhmlw:pckp=true", "-o", nhml_out])

    # Find the actual output files (gpac may add track suffix)
    nhml_files = [f for f in os.listdir(tmpdir) if f.endswith(".nhml")]
    media_files = [f for f in os.listdir(tmpdir) if f.endswith(".media")]
    if not nhml_files or not media_files:
        raise RuntimeError("gpac failed to produce NHML/media output")

    nhml_path = os.path.join(tmpdir, nhml_files[0])
    media_path = os.path.join(tmpdir, media_files[0])

    # 2. MP4Box ISO box dump
    xml_path = os.path.join(tmpdir, "raw.xml")
    _run(["MP4Box", "-diso", raw_path, "-out", xml_path])

    # 3. Extract ALAC decoder params
    decoder_params = None
    if codec == "alac":
        atom_path = os.path.join(tmpdir, "alac.atom")
        r = subprocess.run(
            ["mp4extract", "moov/trak/mdia/minf/stbl/stsd/enca[0]/alac",
             raw_path, atom_path],
            capture_output=True,
        )
        if r.returncode == 0 and os.path.exists(atom_path):
            with open(atom_path, "rb") as f:
                decoder_params = f.read()

    # 4. Parse NHML for sample sizes/durations
    with open(nhml_path) as f:
        nhml_text = f.read()
    nhml_root = ElementTree.fromstring(nhml_text)
    nhml_samples = [
        {
            "length": int(el.get("dataLength", 0)),
            "duration": int(el.get("duration", 0)),
        }
        for el in nhml_root.findall("NHNTSample")
    ]

    # 5. Parse MP4Box XML for SampleDescriptionIndex per fragment
    xml_tree = ElementTree.parse(xml_path)
    xml_root = xml_tree.getroot()
    ns_match = re.match(r"\{(.+?)\}", xml_root.tag)
    ns = f"{{{ns_match.group(1)}}}" if ns_match else ""

    fragment_info = []  # (desc_index, sample_count)
    for moof in xml_root.iter(f"{ns}MovieFragmentBox"):
        desc_index = 0
        for tfhd in moof.iter(f"{ns}TrackFragmentHeaderBox"):
            sdi = tfhd.get("SampleDescriptionIndex")
            if sdi:
                desc_index = int(sdi) - 1
            break
        count = 0
        for trun in moof.iter(f"{ns}TrackRunBox"):
            count += int(trun.get("SampleCount", 0))
        fragment_info.append((desc_index, count))

    sample_desc_indices = []
    for desc_idx, count in fragment_info:
        sample_desc_indices.extend([desc_idx] * count)

    # 6. Read raw media and build samples
    with open(media_path, "rb") as f:
        media_data = f.read()

    samples = []
    offset = 0
    for i, info in enumerate(nhml_samples):
        length = info["length"]
        desc_idx = sample_desc_indices[i] if i < len(sample_desc_indices) else 0
        samples.append(SampleInfo(
            desc_index=desc_idx,
            data=media_data[offset:offset + length],
            duration=info["duration"],
        ))
        offset += length

    # 7. Extract timestamps
    params = {}
    for mvhd in xml_root.iter(f"{ns}MovieHeaderBox"):
        params["CreationTime"] = mvhd.get("CreationTime", "")
        params["ModificationTime"] = mvhd.get("ModificationTime", "")
        break

    return SongInfo(
        samples=samples,
        nhml=nhml_text,
        decoder_params=decoder_params,
        params=params,
    )


def reassemble(
    decrypted_samples: list[bytes],
    song_info: SongInfo,
    codec: str,
    tmpdir: str,
    output_path: str,
):
    """Reassemble decrypted samples into a playable .m4a file."""
    # Write decrypted media blob
    media_path = os.path.join(tmpdir, "dec.media")
    with open(media_path, "wb") as f:
        for sample in decrypted_samples:
            f.write(sample)

    raw_m4a = os.path.join(tmpdir, "dec.m4a")

    if codec == "atmos":
        # Atmos (EC-3): simple remux, no NHML round-trip
        _run(["gpac", "-i", media_path, "-o", raw_m4a])
    else:
        # ALAC/AAC: NHML-based reassembly
        nhml_root = ElementTree.fromstring(song_info.nhml)
        nhml_root.set("baseMediaFile", "dec.media")
        if codec == "alac":
            nhml_root.set("mediaSubType", "alac")
        elif codec == "aac":
            nhml_root.set("mediaSubType", "mp4a")

        nhml_path = os.path.join(tmpdir, "dec.nhml")
        ElementTree.ElementTree(nhml_root).write(
            nhml_path, xml_declaration=True, encoding="utf-8"
        )

        _run(["gpac", "-i", nhml_path, "nhmlr", "-o", raw_m4a])

        # Insert ALAC decoder params
        if codec == "alac" and song_info.decoder_params:
            atom_path = os.path.join(tmpdir, "alac.atom")
            with open(atom_path, "wb") as f:
                f.write(song_info.decoder_params)
            fixed_m4a = os.path.join(tmpdir, "dec_fixed.m4a")
            _run([
                "mp4edit", "--insert",
                f"moov/trak/mdia/minf/stbl/stsd/alac:{atom_path}",
                raw_m4a, fixed_m4a,
            ])
            os.rename(fixed_m4a, raw_m4a)

    # Set M4A brand
    _run(["MP4Box", "-brand", "M4A ", "-ab", "M4A ", "-ab", "mp42", raw_m4a])

    # Fix with ffmpeg
    final_m4a = os.path.join(tmpdir, "final.m4a")
    _run([
        "ffmpeg", "-y", "-i", raw_m4a,
        "-fflags", "+bitexact",
        "-map_metadata", "0",
        "-c:a", "copy", "-c:v", "copy",
        final_m4a,
    ])

    # Move to output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    shutil.move(final_m4a, output_path)


def check_integrity(path: str) -> bool:
    """Verify a .m4a file plays without errors."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", path,
         "-c:a", "pcm_s16le", "-f", "null", "/dev/null"],
        capture_output=True,
    )
    if r.returncode != 0 or r.stderr:
        return False
    return True


def tag_file(path: str, metadata: dict, cover_data: bytes | None = None):
    """Write metadata tags to .m4a file."""
    audio = MP4(path)
    tag_map = {
        "title": "\xa9nam",
        "artist": "\xa9ART",
        "album": "\xa9alb",
        "album_artist": "aART",
        "genre": "\xa9gen",
        "year": "\xa9day",
        "composer": "\xa9wrt",
        "copyright": "cprt",
    }
    for key, atom in tag_map.items():
        if key in metadata and metadata[key]:
            val = metadata[key]
            audio[atom] = [val] if isinstance(val, str) else val

    if "track_number" in metadata and metadata["track_number"]:
        total = metadata.get("track_total", 0) or 0
        audio["trkn"] = [(metadata["track_number"], total)]
    if "disc_number" in metadata and metadata["disc_number"]:
        audio["disk"] = [(metadata["disc_number"], 0)]

    if cover_data:
        audio["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]

    audio.save()


def parse_apple_music_url(url: str) -> tuple[str, str]:
    """Parse Apple Music URL → (type, id). Type is 'song' or 'album'."""
    m = re.match(
        r"https?://music\.apple\.com/\w+/(song|album)/[^/]+/(\d+)", url
    )
    if not m:
        raise ValueError(f"Invalid Apple Music URL: {url}")

    # Check for ?i= (specific song within album URL)
    song_param = re.search(r"[?&]i=(\d+)", url)
    if song_param:
        return "song", song_param.group(1)

    return m.group(1), m.group(2)


def download_song(
    adam_id: str,
    wm: WrapperManagerClient,
    am,
    output_dir: str = "./downloads",
    codec: str = "alac",
) -> str:
    """Download and decrypt a single song. Returns output file path."""
    # 1. Metadata
    print(f"Fetching metadata for {adam_id}...")
    song = am.get_song(adam_id)
    title = song["name"]
    artist = song["artist"]
    album = song["album"]
    print(f"  {artist} - {title} ({album})")

    # 2. M3U8
    print("Getting stream info...")
    m3u8_raw = wm.get_m3u8(adam_id)

    # 3. Parse M3U8
    print("Parsing stream...")
    info = parse_m3u8(m3u8_raw, codec)
    print(f"  codec: {info.codec_id}, keys: {len(info.keys)}")

    # 4. Download encrypted fMP4
    encrypted = download_encrypted(info.uri)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 5. Extract samples
        print("Extracting samples...")
        song_info = extract_samples(encrypted, codec, tmpdir)
        print(f"  {len(song_info.samples)} samples")

        # 6. Decrypt
        print("Decrypting...")
        decrypted = wm.decrypt_samples(adam_id, info.keys, song_info.samples)
        print(f"  decrypted {len(decrypted)} samples")

        # 7. Reassemble
        safe = lambda s: re.sub(r'[<>:"/\\|?*]', "_", s)
        filename = f"{safe(artist)} - {safe(title)}.m4a"
        output_path = os.path.join(output_dir, filename)

        print("Reassembling...")
        reassemble(decrypted, song_info, codec, tmpdir, output_path)

        # 8. Tag
        print("Tagging...")
        metadata = {
            "title": title,
            "artist": artist,
            "album": album,
            "album_artist": song.get("album_artist", artist),
            "genre": song.get("genres", []),
            "year": song.get("release_date", ""),
            "composer": song.get("composer", ""),
            "copyright": song.get("copyright", ""),
            "track_number": song.get("track_number"),
            "track_total": song.get("track_count"),
            "disc_number": song.get("disc_number"),
        }

        cover_data = None
        if song.get("artwork_url"):
            cover_url = song["artwork_url"].replace("{w}", "1200").replace("{h}", "1200")
            try:
                cover_data = httpx.get(cover_url, timeout=30.0).content
            except Exception:
                pass

        tag_file(output_path, metadata, cover_data)

        # 9. Integrity check
        print("Verifying...")
        if not check_integrity(output_path):
            print(f"  WARNING: integrity check failed for {output_path}")
        else:
            print(f"  ✓ verified")

    print(f"  ✓ {output_path}")
    return output_path
