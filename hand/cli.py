#!/usr/bin/env python3
"""
Hand V6 CLI — unified interface for beings to perceive and act.

Usage:
  hand open <target>      # go to a place (app, URL, file)
  hand see                # perceive the current place
  hand do <action>        # execute an action at the current place

Examples:
  hand open Notes
  hand see
  hand do Cmd+N
  hand open https://example.com
  hand do click first link
"""

import sys
from hand.router import route_see, route_do
from hand.place.detect import detect_place, open_place
from hand.session import get_session, reset_session


def cli():
    if len(sys.argv) < 2:
        print("Hand V6 — graphical interface unified framework")
        print("Usage: hand <open|see|do> [target|action]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "open":
        if len(sys.argv) < 3:
            print("Usage: hand open <app|url|path>")
            sys.exit(1)
        
        target = sys.argv[2]
        print(f"→ opening {target}...")
        
        place = open_place(target)
        session = get_session()
        session.place = place
        
        print(f"  place: {place.type} ({place.identifier})")
    
    elif command == "see":
        session = get_session()
        if session.place:
            print(f"  place: {session.place.type} ({session.place.identifier})")
        else:
            print("  (no place set — detecting)")
        
        result = route_see()
        _print_result(result)
    
    elif command == "do":
        if len(sys.argv) < 3:
            print("Usage: hand do <action>")
            sys.exit(1)
        
        action = sys.argv[2]
        print(f"→ {action}")
        
        result = route_do(action)
        _print_result(result)
    
    elif command == "reset":
        reset_session()
        print("→ session reset")
    
    elif command == "where":
        session = get_session()
        if session.place:
            print(f"  {session.place.type}: {session.place.identifier}")
        else:
            print("  (nowhere)")
    
    else:
        print(f"Unknown command: {command}")
        print("Try: open, see, do, where, reset")
        sys.exit(1)


def _print_result(result: dict):
    """Pretty-print a perception or action result."""
    import json
    if result is None:
        print("  (no result)")
        return
    
    method = result.get("method", "unknown")
    
    if "error" in result:
        print(f"  [{method}] error: {result['error']}")
        if "details" in result:
            for d in result["details"]:
                print(f"    {d}")
        return
    
    if method == "ax_app":
        print(f"  [{method}] {result.get('app', '?')}: {result.get('note_count', '?')} notes")
        names = result.get('note_names', [])
        if names:
            for n in names[:10]:
                print(f"    • {n}")
            if len(names) > 10:
                print(f"    ... and {len(names) - 10} more")
    
    elif method == "vision_ocr":
        print(f"  [{method}] capture: {result.get('capture_ms', '?')}ms, ocr: {result.get('ocr_ms', '?')}ms, {result.get('total_lines', '?')} lines")
        by_conf = result.get('by_confidence', {})
        if by_conf.get('high'):
            print(f"  [high confidence]")
            for t in by_conf['high'][:15]:
                print(f"    {t}")
    
    elif method == "keystroke":
        print(f"  [{method}] {result.get('action')} → {result.get('resolved')} (exit: {result.get('exit_code')})")
        if result.get('stderr'):
            print(f"    stderr: {result['stderr']}")
    
    else:
        print(f"  [{method}]")
        # Print keys except method
        for k, v in result.items():
            if k != "method" and k != "all_text":
                if isinstance(v, str) and len(v) < 200:
                    print(f"    {k}: {v}")
                elif isinstance(v, int):
                    print(f"    {k}: {v}")


if __name__ == "__main__":
    cli()
