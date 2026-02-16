"""
Интеграция с WireGuard: вызов add-wg-client.sh и отзыв peer.
При локальном запуске без WG_SCRIPT_PATH возвращает мок-данные.
"""
import asyncio
import re
from pathlib import Path

from app.config import settings


class WireGuardService:
    def __init__(self):
        self.script_path = settings.wg_script_path
        self.conf_path = settings.wg_conf_path
        self.clients_dir = Path(settings.wg_clients_dir)
        self.server_endpoint = settings.server_endpoint
        self.wg_port = settings.wg_port

    async def add_client(self, client_name: str) -> dict:
        """
        Запускает add-wg-client.sh на сервере и возвращает данные клиента.
        Возвращает: { "allowed_ip", "private_key", "public_key", "config_content", "conf_path" }
        """
        if not self.script_path or not Path(self.script_path).exists():
            return self._mock_add_client(client_name)

        proc = await asyncio.create_subprocess_exec(
            "sudo",
            self.script_path,
            client_name,
            self.server_endpoint,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**__import__("os").environ, "WG_PORT": str(self.wg_port)},
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Script failed: {stderr.decode() or stdout.decode()}")

        # Читаем созданный конфиг
        conf_file = self.clients_dir / f"{client_name}.conf"
        if not conf_file.exists():
            raise RuntimeError(f"Config file not created: {conf_file}")

        config_content = conf_file.read_text(encoding="utf-8", errors="replace")

        # Парсим ключи и IP из конфига
        private_key = self._extract(config_content, "PrivateKey")
        public_key = self._extract(config_content, "PublicKey", section="Peer")
        allowed_ip = self._extract(config_content, "Address").split("/")[0]

        return {
            "allowed_ip": allowed_ip,
            "private_key": private_key,
            "public_key": public_key,
            "config_content": config_content,
            "conf_path": str(conf_file),
        }

    def _extract(self, config: str, key: str, section: str = "Interface") -> str:
        in_section = False
        for line in config.splitlines():
            line = line.strip()
            if line == "[Interface]":
                in_section = section == "Interface"
            elif line == "[Peer]":
                in_section = section == "Peer"
            elif in_section and line.startswith(key + " "):
                return line.split("=", 1)[1].strip()
        return ""

    def _mock_add_client(self, client_name: str) -> dict:
        """Мок для локального теста без WireGuard."""
        import secrets
        base = "10.66.0"
        # В моке просто даём фиктивный IP (реальный скрипт на сервере выдаст свой)
        allowed_ip = f"{base}.2"
        private_key = secrets.token_urlsafe(32)
        public_key = secrets.token_urlsafe(32)
        config_content = f"""[Interface]
PrivateKey = {private_key}
Address = {allowed_ip}/32
DNS = 1.1.1.1, 1.0.0.1

[Peer]
PublicKey = SERVER_PUBKEY_PLACEHOLDER
Endpoint = {self.server_endpoint}:{self.wg_port}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
        return {
            "allowed_ip": allowed_ip,
            "private_key": private_key,
            "public_key": public_key,
            "config_content": config_content,
            "conf_path": "",
        }

    async def revoke_client(self, public_key: str) -> None:
        """
        Удаляет peer из wg0.conf по публичному ключу и применяет конфиг.
        """
        if not self.conf_path or not Path(self.conf_path).exists():
            return  # мок: ничего не делаем

        path = Path(self.conf_path)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.strip() == "[Peer]":
                block = [line]
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("["):
                    block.append(lines[i])
                    i += 1
                if public_key not in "\n".join(block):
                    result.extend(block)
            else:
                result.append(line)
                i += 1
        path.write_text("\n".join(result), encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            "sudo", "wg", "syncconf", "wg0", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        strip_proc = await asyncio.create_subprocess_exec(
            "wg-quick", "strip", "wg0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        strip_out, _ = await strip_proc.communicate()
        await proc.communicate(input=strip_out)


wireguard_service = WireGuardService()
