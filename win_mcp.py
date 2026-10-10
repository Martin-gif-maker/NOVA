# win_mcp.py — MCP tool servers: connect them, offer their tools to the AI, and the window to manage them.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import json
import logging
from PySide6.QtWidgets import QDialog
import mcp_client
import keystore
import tools as computer_tools
from i18n import tr
from schemas import TOOLS_SCHEMA
from dialogs import McpDialog

log = logging.getLogger("nova")


class McpMixin:
    SECRETS_NAME = "mcp_secrets"            # one Keychain entry holding every server's tokens

    def _mcp_secrets(self) -> dict:
        try:
            data = json.loads(keystore.get_secret(self.SECRETS_NAME) or "{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def _seal_mcp_settings(self, servers: dict) -> dict:
        """Move tokens (environment values, HTTP headers) into the Keychain; the settings keep only placeholders.
        Returns the servers with their real values, ready to start. If the Keychain is unavailable the values
        stay in the settings file, as before."""
        safe, secrets = mcp_client.split_secrets(servers, self._mcp_secrets())
        if keystore.set_secret(self.SECRETS_NAME, json.dumps(secrets)):
            if safe != self.config.get("mcp_servers", {}):
                self.config["mcp_servers"] = safe; self._save_config()
            return mcp_client.join_secrets(safe, secrets)
        log.warning("Keychain unavailable - MCP server tokens stay in the settings file")
        self.config["mcp_servers"] = mcp_client.join_secrets(safe, secrets); self._save_config()
        return self.config["mcp_servers"]

    def _start_mcp(self):
        computer_tools.MCP = mcp_client.Manager(on_change=self._bridge.mcp_changed.emit)
        servers = self.config.get("mcp_servers", {})
        computer_tools.MCP.apply(self._seal_mcp_settings(servers) if servers else {})

    def _on_mcp_changed(self, server):
        """A server connected, failed or was removed (called on the window's thread)."""
        gone = set(computer_tools.unregister_mcp_server(server.name))
        if gone:
            TOOLS_SCHEMA[:] = [s for s in TOOLS_SCHEMA if s.get("function", {}).get("name") not in gone]
        manager = computer_tools.MCP
        if manager is None or manager.servers.get(server.name) is not server:
            return                                          # removed or replaced: its tools are gone, nothing to add
        if server.status == "ready":
            added = computer_tools.register_mcp_server(server)
            TOOLS_SCHEMA.extend(added)
            if not gone:
                self.chat_area.add_message(tr("🔌  {} is connected: {} tools.").format(server.name, len(added)), "system", self._theme)
        elif server.status == "error":
            self.chat_area.add_message(tr("⚠️  The tool server “{}” could not be connected: {}").format(server.name, server.error),
                                       "system", self._theme)

    def _mcp_status(self) -> dict:
        m = computer_tools.MCP
        return {n: (s.status, len(s.tools), s.error) for n, s in (m.servers.items() if m else [])}

    def _show_mcp_dialog(self, parent=None):
        dlg = McpDialog(self._theme, self.config.get("mcp_servers", {}), self._mcp_status, parent or self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            ready = self._seal_mcp_settings(dlg.servers())             # tokens go to the Keychain, not the settings file
            self._save_config()
            if computer_tools.MCP: computer_tools.MCP.apply(ready)

    def _stop_mcp(self):
        m, computer_tools.MCP = computer_tools.MCP, None
        if m:
            try: m.stop_all()
            except Exception as e: log.info("stopping MCP servers: %s", e)
