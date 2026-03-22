FROM --platform=linux/amd64 ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download wrapper release
ARG WRAPPER_URL=https://github.com/WorldObservationLog/wrapper/releases/download/Wrapper.x86_64.1dac7bb/Wrapper.x86_64.1dac7bb.zip
RUN curl -L -o wrapper.zip "$WRAPPER_URL" \
    && unzip wrapper.zip \
    && rm wrapper.zip \
    && chmod +x wrapper

ENTRYPOINT ["./wrapper"]
EXPOSE 10020 20020 30020
