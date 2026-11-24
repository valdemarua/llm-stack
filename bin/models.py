#!/usr/bin/env python3
"""Manage local chat models through the two internal APIs."""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import model_catalog

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text

def request(service, path, method="GET", data=None, stream=False, diagnostic=False):
    base = "http://ollama:11434" if service == "Ollama" else "http://127.0.0.1:4000"
    headers = {"Content-Type": "application/json"}
    if service == "LiteLLM":
        key = os.environ.get("LITELLM_MASTER_KEY")
        if not key:
            raise RuntimeError("LiteLLM master key is missing.")
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base + path, headers=headers, method=method,
                                 data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=300 if stream else 30) as response:
            if stream:
                done = False
                previous = None
                for line in response:
                    event = json.loads(line)
                    if event.get("error"):
                        raise RuntimeError("Ollama download failed.")
                    status = event.get("status")
                    if status and status != previous:
                        print("  " + status, flush=True)
                        previous = status
                    done = done or status == "success"
                if not done:
                    raise RuntimeError("Ollama download did not complete.")
                return
            body = response.read()
            if diagnostic:
                try:
                    return response.status, json.loads(body) if body else None
                except ValueError:
                    return response.status, None
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        if diagnostic:
            try:
                body = json.loads(exc.read(65536))
            except (ValueError, OSError):
                body = None
            return exc.code, body
        raise RuntimeError(f"{service} {path}: HTTP {exc.code}") from None
    except (OSError, urllib.error.URLError):
        raise RuntimeError(f"{service} is unavailable; check container health and logs.") from None

def doctor():
    """Probe endpoints independently; never print response secrets."""
    probes = [
        ("Ollama", "/api/tags"),
        ("LiteLLM", "/health/liveliness"),
        ("LiteLLM", "/health/readiness"),
        ("LiteLLM", "/v1/models"),
        ("LiteLLM", "/model/info"),
        ("LiteLLM", "/v2/model/info"),
        ("LiteLLM", "/model_group/info"),
    ]
    failed = False
    print(paint("LLM Stack · Diagnostics", 36))
    for service, path in probes:
        label = f"{service} {path}"
        try:
            status, body = request(service, path, diagnostic=True)
            success = 200 <= status < 300
            failed |= not success
            detail = ""
            if isinstance(body, dict):
                for field in ("models", "data"):
                    if isinstance(body.get(field), list):
                        detail = f" · {len(body[field])} entries"
                        break
                if type(body.get("total_count")) is int:
                    detail += f" · total {body['total_count']}"
                if not success:
                    error = body.get("error", body.get("detail"))
                    if isinstance(error, dict):
                        error = error.get("message")
                    # Only emit recognized diagnostic categories, never raw text.
                    if isinstance(error, str):
                        lower = error.lower()
                        for pattern, category in (
                            ("no models", "no models"),
                            ("no model", "no model"),
                            ("router", "router-related"),
                            ("database", "database-related"),
                            ("prisma", "database-related"),
                            ("none", "null-related"),
                            ("auth", "authentication-related"),
                        ):
                            if pattern in lower:
                                detail += " · " + category
                                break
            print(f"{label:<34} {paint('HTTP ' + str(status), 32 if success else 31)}{detail}", flush=True)
        except (RuntimeError, ValueError, OSError):
            failed = True
            print(f"{label:<34} {paint('Request failed', 31)}", flush=True)
    return 1 if failed else 0


def registered_routes():
    # V1 can return HTTP 500 on a cold start with no registered models.
    page = request("LiteLLM", "/v2/model/info?page=1&size=50")
    total = page["total_count"]
    if type(total) is not int or total < 0 or not isinstance(page["data"], list):
        raise RuntimeError("Invalid LiteLLM inventory response.")
    if total == 0:
        if page["data"]:
            raise RuntimeError("Inconsistent LiteLLM inventory response.")
        return []
    # V1 returns the full inventory and connection metadata; V2 may hide api_base.
    routes = request("LiteLLM", "/model/info")["data"]
    if not isinstance(routes, list) or len(routes) != total:
        raise RuntimeError("LiteLLM inventory changed or is incomplete; retry.")
    return routes

def local_model(route):
    p = params(route)
    model = p.get("model", "")
    if (p.get("api_base") or "").rstrip("/") != "http://ollama:11434":
        return None
    for prefix in ("ollama_chat/", "ollama/"):
        if model.startswith(prefix):
            tag = model[len(prefix):]
            return tag if ":" in tag else tag + ":latest"
    return None

def inventory():
    names = {m["name"] for m in request("Ollama", "/api/tags")["models"]}
    routes = registered_routes()
    return names, routes

def params(route):
    return route.get("litellm_params") or {}

def matches(route, name):
    return (route.get("model_name") == name
            and params(route).get("model") == "ollama_chat/" + name
            and params(route).get("api_base") == "http://ollama:11434")

def ok(message):
    print(paint("✓ " + message, 32))

def main():
    parser = argparse.ArgumentParser(prog="bin/models", description="Discover, install and manage local Ollama chat models.", epilog="Examples: bin/models search qwen; bin/models tags qwen3; bin/models add qwen3:4b")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Show installed models and gateway registrations")
    search = commands.add_parser("search", help="Browse selected developers in the public Ollama catalog", description="Browse public search results for selected model developers. --all queries known family prefixes for broader coverage.")
    search.add_argument("query", nargs="?", help="Filter by model name")
    search.add_argument("--all", action="store_true", help="Expand search across known families, not the entire Ollama registry")
    tags = commands.add_parser("tags", help="Show downloadable model tags and file sizes")
    tags.add_argument("family", help="Library model name, e.g. qwen3")
    commands.add_parser("doctor", help="Probe internal APIs without changing state")
    for command in ("add", "remove"):
        commands.add_parser(command, help={"add": "Download and register an explicit chat model tag", "remove": "Unregister and delete a model after confirmation"}[command]).add_argument("model", help="Explicit tag, e.g. qwen3:4b")
    if len(sys.argv) == 1:
        parser.print_help()
        return
    args = parser.parse_args()
    if args.command == "search":
        return model_catalog.search(args.query, args.all)
    if args.command == "tags":
        return model_catalog.tags(args.family)
    if args.command == "doctor":
        sys.exit(doctor())
    name = getattr(args, "model", None)
    if name and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./-]*:[a-zA-Z0-9][a-zA-Z0-9_.-]*", name):
        parser.error("Use an explicit model tag, e.g. qwen3:4b.")
    print(paint("LLM Stack · Models", 36), flush=True)
    installed, routes = inventory()
    if args.command == "list":
        names = sorted(installed | {local_model(r) or r["model_name"] for r in routes})
        width = max([len("MODEL")] + [len(n) for n in names]) + 3
        print(f"{'MODEL':<{width}} {'OLLAMA':<14} LITELLM (public name)")
        for n in names:
            local = "Installed" if n in installed else "Missing"
            linked = [r for r in routes if local_model(r) == n]
            other = [r for r in routes if local_model(r) is None and r["model_name"] == n]
            remote = ("Registered: " + ", ".join(r["model_name"] for r in linked)
                      if linked else "Other route" if other else "Missing")
            if other and linked:
                remote += " (name conflict)"
            print(f"{n:<{width}} {paint(f'{local:<14}', 32 if local == 'Installed' else 33)} {paint(remote, 32 if remote.startswith('Registered:') else 33)}")
        if not names:
            print("No models. Browse https://ollama.com/library")
        return
    same = [r for r in routes if r["model_name"] == name]
    if args.command == "add":
        aliases = [r for r in routes if local_model(r) == name and not matches(r, name)]
        if aliases:
            raise RuntimeError("Model already has a different route; manage its alias manually first.")
        if same and (len(same) != 1 or not matches(same[0], name)):
            raise RuntimeError("Name is already used by a different or duplicate route.")
        if name not in installed:
            request("Ollama", "/api/pull", "POST", {"model": name, "stream": True}, stream=True)
        ok("Installed: " + name)
        if not same:
            try:
                request("LiteLLM", "/model/new", "POST", {"model_name": name, "litellm_params": {"model": "ollama_chat/" + name, "api_base": "http://ollama:11434"}})
            except RuntimeError as exc:
                raise RuntimeError(str(exc) + "; weights retained. Retry add.") from None
        ok("Registered: " + name)
        return
    references = [r for r in routes if params(r).get("model") in ("ollama_chat/" + name, "ollama/" + name, "ollama_chat/" + name.removesuffix(":latest"), "ollama/" + name.removesuffix(":latest"))]
    if any(local_model(r) == name and not matches(r, name) for r in routes) or len(references) > 1 or any(not matches(r, name) for r in references) or any(not matches(r, name) for r in same):
        raise RuntimeError("Conflicting routes or aliases exist; manage them manually first.")
    if not same and name not in installed:
        ok("Already absent: " + name)
        return
    if not sys.stdin.isatty():
        raise RuntimeError("Removal requires an interactive terminal.")
    if input(f"Remove {name} from LiteLLM and Ollama? [y/N] ").lower() != "y":
        print("Cancelled.")
        return
    if same:
        route_id = (same[0].get("model_info") or {}).get("id")
        if not route_id:
            raise RuntimeError("Missing route ID; remove manually.")
        request("LiteLLM", "/model/delete", "POST", {"id": route_id})
        ok("Registration removed")
    if name in installed:
        request("Ollama", "/api/delete", "DELETE", {"model": name})
    ok("Removed: " + name)

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError, EOFError) as exc:
        # Do not print arbitrary API response content or secrets.
        message = str(exc) if isinstance(exc, RuntimeError) else "Unexpected API response or input."
        print(paint("✗ " + message, 31), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the command to reconcile state.", file=sys.stderr)
        sys.exit(130)
