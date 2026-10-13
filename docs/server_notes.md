# Server Notes

## Git Baseline

- Server repository: `../server`
- Initial commit: `5efe0bd4c5c93c5fdc7de5bcd5d2268fe8a8a3ca`
- Initial `git status --short`: clean

This baseline was captured before making analytics project changes. The analytics runner checks the server repository at the end of every experiment run and reports pre-existing server status entries separately from newly appearing entries.

## Build Procedure and Dependencies

The server `Makefile` builds with:

```bash
g++ -std=c++17 -Wall -Wextra -O2 -Iinclude -pthread src/main.cpp src/server.cpp src/HttpRequest.cpp src/HttpResponse.cpp -o build/server
```

Dependencies observed from the source and build file:

- GNU Make
- A C++17 compiler such as `g++`
- POSIX/Linux networking APIs, including sockets, `epoll`, `poll`, and `fcntl`
- pthread support

Per the project boundary rules, this analytics project does not run `make` directly inside `../server`. The Dockerfile builds the server from a read-only named Docker build context and copies the source inside the image before running `make`.

## Executable

- Build target: `build/server`
- Docker runtime path used by this project: `/app/server`

## Listening Address and Port

The server binds to `INADDR_ANY` on the configured port. The default port is `8080`.

The Docker runner publishes the container port on `127.0.0.1:${HOST_PORT}`. By default, the benchmark target is:

```text
http://127.0.0.1:8080/
```

## Runtime Arguments

`src/main.cpp` accepts positional arguments:

1. Port, default `8080`
2. Static file root, default `public`
3. Worker thread count, default `4`

The Docker runner starts it as:

```bash
/app/server 8080 /app/public 4
```

## HTTP Endpoints

The server implements static file serving for `GET` requests:

- `GET /` maps to `/index.html`
- Any clean path without `..` maps to a file under the configured root
- Unsupported methods return `405 Method Not Allowed`
- Missing files return `404 Not Found`
- Invalid request parsing returns `400 Bad Request`
- Paths containing `..` return `403 Forbidden`

The checked-in static file `public/index.html` exists, so the default endpoint `/` can be benchmarked without extra setup.

## Metrics Exposed by the Server

No built-in metrics endpoint, request counters, latency metrics, CPU metrics, or memory metrics were found in the server source. This project therefore collects benchmark metrics from wrk2 and resource metrics from Docker.

