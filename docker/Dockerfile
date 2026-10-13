# syntax=docker/dockerfile:1.7

FROM gcc:13-bookworm AS build

WORKDIR /work/server

# Build from a named, read-only Docker build context:
#   docker build --build-context server=../server -f docker/Dockerfile .
# The source is copied inside the image before make runs, so ../server is never modified.
RUN --mount=type=bind,from=server,source=.,target=/readonly-server,readonly \
    cp -a /readonly-server/. /work/server && \
    make

FROM gcc:13-bookworm

WORKDIR /app
COPY --from=build /work/server/build/server /app/server
COPY --from=build /work/server/public /app/public

EXPOSE 8080
ENTRYPOINT ["/app/server"]
CMD ["8080", "/app/public", "4"]

