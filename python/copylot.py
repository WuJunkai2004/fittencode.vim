import json
import os
import sys
from typing import Optional

from agent import Agent
from config import Config
from git import gitDiff, gitLog
from provider import ProviderBuild


class CopylotDaemon:
    def __init__(self, config_path: Optional[str] = None):
        # Determine config path: Priority 1. Constructor 2. Default ~/.vim/ai_config.toml
        if (
            not config_path
            or not os.path.isfile(config_path)
            or not os.access(config_path, os.R_OK)
        ):
            config_path = os.path.expanduser("~/.vim/ai_config.toml")

        self.config_path = config_path
        self.config = Config(config_path)
        self._buffer = b""
        try:
            self.provider = ProviderBuild(config_path)
            self.agent = Agent(self.provider)
        except Exception as e:
            self.log(f"Failed to initialize provider: {e}")
            exit(1)

    def log(self, msg):
        sys.stderr.write(f"LOG: {msg}\n")
        sys.stderr.flush()

    def response(self, resp_type: str, content):
        """Sends a JSON response separated by \n\n."""
        # type: answer, ends, error, gitmsg
        response_obj = {"type": resp_type, "content": content}
        body = json.dumps(response_obj, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(body + b"\n\n")
        sys.stdout.buffer.flush()

    def handle_query(self, content: list):
        """Handle 'query' action."""
        if not self.provider:
            self.response("error", "Provider not initialized. Check your config.")
            return

        # content is expected to be a list of messages: [{"role": "user", "content": "..."}]
        if not isinstance(content, list):
            self.response("error", "Content must be a list of messages.")
            return

        try:
            for msg in self.provider.stream(content):
                self.response("answer", msg)
        except Exception as e:
            self.response("error", f"AI Provider Error: {e}")
        finally:
            self.response("ends", "")

    def handle_agent(self, content: list):
        """Handle 'agent' action."""
        if not self.agent:
            self.response("error", "Agent not initialized. Check your config.")
            return

        if not isinstance(content, list):
            self.response("error", "Content must be a list of messages.")
            return

        try:
            for step in self.agent.act(content):
                pretty_text = self.agent.pretty(step)
                if pretty_text:
                    self.response("answer", pretty_text)
        except Exception as e:
            self.response("error", f"AI Agent Error: {e}")
        finally:
            self.response("ends", "")

    def handle_stop(self):
        """Handle 'stop' action."""
        # Placeholder for stopping current generation if streaming is implemented
        self.log("Stop requested (not fully implemented)")
        self.response("ends", "")

    def handle_commit_message(self):
        """Handle 'commit_message' action."""
        if not self.provider:
            self.response("error", "Provider not initialized.")
            return

        try:
            diff = gitDiff(cached=True)
            # Truncate diff if it's too long
            diff_lines = diff.splitlines()
            if len(diff_lines) > 200:
                diff = (
                    "\n".join(diff_lines[:200]) + "\n\n(Diff truncated for brevity...)"
                )

            history = gitLog(n=10)
            if not diff.strip() or diff.startswith("An error occurred"):
                self.response("answer", f"No staged changes found or error: {diff}")
            else:
                # Use custom provider if configured
                commit_provider_name = self.config.get("commit.provider")
                provider = self.provider
                if commit_provider_name:
                    try:
                        provider = ProviderBuild(self.config_path, commit_provider_name)
                    except Exception as e:
                        self.log(
                            f"Failed to build commit provider '{commit_provider_name}': {e}"
                        )

                # Use custom prompt if configured
                commit_prompt = self.config.get("commit.prompt")
                system_content = (
                    commit_prompt
                    if commit_prompt is not None
                    else "You are a git commit expert who mimics the user's specific writing style based on history."
                )

                prompt = (
                    f"The following is the user's recent commit history:\n"
                    f"{history}\n\n"
                    f"Please generate a concise git commit message for the following diff, "
                    f"imitating the user's style (e.g., prefix usage, tone, length):\n\n"
                    f"{diff}"
                )
                messages = [
                    {
                        "role": "system",
                        "content": system_content,
                    },
                    {"role": "user", "content": prompt},
                ]
                ai_res = provider.send(messages)
                self.response("gitmsg", ai_res)
        except Exception as e:
            self.response("error", f"Git Commit Error: {str(e)}")
        finally:
            self.response("ends", "")

    def handle_mcp(self, content):
        """Placeholder for Model Context Protocol (MCP) support."""
        # Future implementation for MCP
        self.log(f"MCP action received: {content}")
        self.response("error", "MCP support is not yet implemented.")
        self.response("ends", "")

    def dispatch(self, msg):
        """Dispatch message to appropriate handler based on 'action'."""
        action = msg.get("action")
        content = msg.get("content", [])

        if action == "query":
            self.handle_query(content)
        elif action == "agent":
            self.handle_agent(content)
        elif action == "stop":
            self.handle_stop()
        elif action == "commit_message":
            self.handle_commit_message()
        elif action == "mcp":
            self.handle_mcp(content)
        else:
            self.response("error", f"Unknown action: {action}")
            self.response("ends", "")

    def read(self) -> tuple[Optional[dict], str]:
        """Reads a message from stdin and returns the parsed JSON and error string."""
        try:
            while True:
                line = sys.stdin.buffer.readline()
                if not line or not isinstance(line, bytes):
                    return None, "EOF"
                if line == b"\n":
                    if not self._buffer:
                        continue  # Ignore empty lines
                    data = self._buffer
                    self._buffer = b""
                    return json.loads(data.decode("utf-8")), ""
                self._buffer += line
        except Exception as e:
            return None, str(e)

    def run(self):
        while True:
            msg, err = self.read()
            self.log(f"Received message: {msg}, Error: {err}")
            if err:
                if err == "EOF":
                    break
                self.response("error", f"Failed to read message: {err}")
                continue
            if msg:
                self.dispatch(msg)


if __name__ == "__main__":
    config_path_arg = sys.argv[1] if len(sys.argv) > 1 else None
    daemon = CopylotDaemon(config_path_arg)
    daemon.run()
