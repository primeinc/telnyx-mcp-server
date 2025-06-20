#!/usr/bin/env python3
import asyncio
from datetime import datetime


async def handle_client(reader, writer):
    addr = writer.get_extra_info("peername")
    print(f"\n{'=' * 80}")
    print(f"[{datetime.now()}] New connection from {addr}")
    print("=" * 80)

    try:
        # Read raw data
        data = await reader.read(4096)

        if data:
            print("RAW BYTES:")
            print("-" * 40)
            # Print hex dump
            for i in range(0, len(data), 16):
                chunk = data[i : i + 16]
                hex_str = " ".join(f"{b:02x}" for b in chunk)
                ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"{i:04x}  {hex_str:<48}  {ascii_str}")

            print("-" * 40)
            print("DECODED AS STRING:")
            print("-" * 40)
            try:
                decoded = data.decode("utf-8", errors="replace")
                print(decoded)
            except Exception:
                print("<COULD NOT DECODE>")
            print("-" * 40)

            # Parse the request path
            request_line = decoded.split("\r\n")[0] if decoded else ""
            path = (
                request_line.split(" ")[1] if len(request_line.split(" ")) > 1 else ""
            )

            # Fake appropriate responses based on path
            if path == "/.well-known/oauth-protected-resource":
                response_body = '{"resource":"http://localhost:8000/mcp","www-authenticate":"Bearer"}'
                response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(response_body)}\r\n\r\n{response_body}".encode()
            elif path == "/.well-known/oauth-authorization-server":
                response_body = '{"issuer":"http://localhost:8000","authorization_endpoint":"http://localhost:8000/authorize","token_endpoint":"http://localhost:8000/token","registration_endpoint":"http://localhost:8000/register","response_types_supported":["code","token"],"grant_types_supported":["authorization_code","implicit"],"token_endpoint_auth_methods_supported":["client_secret_post","client_secret_basic"],"scopes_supported":["openid","profile","email","offline_access"],"code_challenge_methods_supported":["S256"]}'
                response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(response_body)}\r\n\r\n{response_body}".encode()
            elif path == "/.well-known/openid-configuration":
                response_body = '{"issuer":"http://localhost:8000","authorization_endpoint":"http://localhost:8000/authorize","token_endpoint":"http://localhost:8000/token","userinfo_endpoint":"http://localhost:8000/userinfo","jwks_uri":"http://localhost:8000/.well-known/jwks.json","response_types_supported":["code","token","id_token"],"subject_types_supported":["public"],"id_token_signing_alg_values_supported":["RS256"],"scopes_supported":["openid","profile","email"],"token_endpoint_auth_methods_supported":["client_secret_post","client_secret_basic"],"claims_supported":["sub","name","email","preferred_username"],"code_challenge_methods_supported":["S256"]}'
                response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(response_body)}\r\n\r\n{response_body}".encode()
            elif path == "/register" and request_line.startswith("POST"):
                # Fake client registration response
                response_body = '{"client_id":"test-client-123","client_secret":"test-secret-456","redirect_uris":["http://localhost:6274/oauth-callback"],"grant_types":["authorization_code"],"response_types":["code"],"token_endpoint_auth_method":"client_secret_post"}'
                response = f"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(response_body)}\r\n\r\n{response_body}".encode()
            elif path.startswith("/authorize"):
                # Fake authorization redirect - extract redirect_uri from query
                import urllib.parse

                query_start = path.find("?")
                if query_start > 0:
                    query_string = path[query_start + 1 :]
                    params = urllib.parse.parse_qs(query_string)
                    redirect_uri = params.get(
                        "redirect_uri", ["http://localhost:6274/oauth/callback/debug"]
                    )[0]
                    # Redirect back with fake auth code
                    redirect_url = f"{redirect_uri}?code=fake-auth-code-123&state=test"
                    response = f"HTTP/1.1 302 Found\r\nLocation: {redirect_url}\r\nContent-Length: 0\r\n\r\n".encode()
                else:
                    response = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 11\r\n\r\nBad Request"
            elif path == "/token" and request_line.startswith("POST"):
                # Fake token response
                response_body = '{"access_token":"fake-access-token-456","token_type":"Bearer","expires_in":3600,"refresh_token":"fake-refresh-token-789","scope":"openid profile email offline_access"}'
                response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(response_body)}\r\n\r\n{response_body}".encode()
            elif request_line.startswith("OPTIONS"):
                # Handle CORS preflight
                response = b"HTTP/1.1 200 OK\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, POST, OPTIONS\r\nAccess-Control-Allow-Headers: *\r\nContent-Length: 0\r\n\r\n"
            else:
                response = (
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\n\r\nNot Found"
                )

            writer.write(response)
            await writer.drain()
        else:
            print("NO DATA RECEIVED - Empty connection")

    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        writer.close()
        await writer.wait_closed()
        print(f"Connection closed from {addr}")
        print("=" * 80)


async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8000)

    print("Raw debug server listening on port 8000")
    print("Waiting for connections...\n")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
