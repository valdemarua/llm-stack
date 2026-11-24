#!/usr/bin/env python3
"""Manage local chat models through the two internal APIs."""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text

def request(service, path, method="GET", data=None, stream=False):
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
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{service} {path}: HTTP {exc.code}") from None
    except (OSError, urllib.error.URLError):
        raise RuntimeError(f"{service} is unavailable; check container health and logs.") from None

def inventory():
    names = {m["name"] for m in request("Ollama", "/api/tags")["models"]}
    routes = request("LiteLLM", "/model/info")["data"]
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
    parser = argparse.ArgumentParser(prog="bin/models")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    for command in ("add", "remove"):
        commands.add_parser(command).add_argument("model")
    args = parser.parse_args()
    name = getattr(args, "model", None)
    if name and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./-]*:[a-zA-Z0-9][a-zA-Z0-9_.-]*", name):
        parser.error("Use an explicit model tag, e.g. qwen3:4b.")
    print(paint("LLM Stack · Models", 36), flush=True)
    installed, routes = inventory()
    if args.command == "list":
        names = sorted(installed | {r["model_name"] for r in routes})
        width = max([len("MODEL")] + [len(n) for n in names]) + 3
        print(f"{'MODEL':<{width}} {'OLLAMA':<14} LITELLM")
        for n in names:
            local = "Installed" if n in installed else "Missing"
            remote = ("Registered" if any(matches(r, n) for r in routes)
                      else "Other route" if any(r["model_name"] == n for r in routes) else "Missing")
            print(f"{n:<{width}} {paint(f'{local:<14}', 32 if local == 'Installed' else 33)} {paint(remote, 32 if remote == 'Registered' else 33)}")
        if not names:
            print("No models. Browse https://ollama.com/library")
        return
    same = [r for r in routes if r["model_name"] == name]
    if args.command == "add":
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
    if len(references) > 1 or any(not matches(r, name) for r in references) or any(not matches(r, name) for r in same):
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
