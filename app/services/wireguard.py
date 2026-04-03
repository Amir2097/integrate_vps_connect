"""
Интеграция с WireGuard: вызов add-wg-client.sh и отзыв peer.
При локальном запуске без WG_SCRIPT_PATH (или если скрипт не найден) — мок:
валидный по формату .conf для импорта/QR, но файл на диске не создаётся и туннель
к реальному серверу не подключится без настоящего peer на WG.
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
        self.use_sudo = getattr(settings, "wg_use_sudo", True)

    async def add_client(self, client_name: str) -> dict:
        """
        Запускает add-wg-client.sh на сервере и возвращает данные клиента.
        Возвращает: { "allowed_ip", "private_key", "public_key", "config_content", "conf_path" }
        """
        if not self.script_path:
            return self._mock_add_client(client_name)
        script_path = Path(self.script_path)
        if not script_path.exists():
            print(f"[WG] Script not found at {self.script_path}, using mock. Check WG_SCRIPT_PATH in .env")
            return self._mock_add_client(client_name)

        # С sudo (по умолчанию) или напрямую от пользователя процесса (WG_USE_SUDO=false).
        # Sudo не передаёт env в скрипт — передаём флаг «сделать читаемым» третьим аргументом (1).
        os_environ = __import__("os").environ
        base_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        if self.use_sudo:
            cmd = [
                "sudo",
                self.script_path,
                client_name,
                self.server_endpoint,
                "1",  # третий аргумент: скрипт сделает chmod 644, чтобы amir мог прочитать конфиг
            ]
            env = None
            # В логах видно, что третий аргумент "1" передаётся (для отладки прав 644)
            print(f"[WG] add_client cmd: {' '.join(cmd)}", flush=True)
        else:
            # Явно передаём переменные через env (пути из .env — скрипт может искать конфиг не в /etc/wireguard)
            cmd = [
                "/usr/bin/env",
                f"PATH={base_path}",
                "WG_SKIP_ROOT_CHECK=1",
                f"WG_PORT={self.wg_port}",
                f"SERVER_ENDPOINT={self.server_endpoint}",
                f"WG_CONF={self.conf_path}",
                f"WG_CLIENTS_DIR={self.clients_dir}",
                self.script_path,
                client_name,
                self.server_endpoint,
            ]
            env = None  # env уже задан в командной строке через /usr/bin/env
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Script failed: {stderr.decode() or stdout.decode()}")

        out = stdout.decode("utf-8", errors="replace")

        # В клиентском .conf в [Peer] записан PublicKey сервера, не клиента — ключ клиента скрипт выводит в stdout
        public_key = self._parse_stdout_key(out, "WG_CLIENT_PUBLIC_KEY")
        allowed_ip_from_stdout = self._parse_stdout_key(out, "WG_CLIENT_IP")

        # Читаем созданный конфиг
        conf_file = self.clients_dir / f"{client_name}.conf"
        if not conf_file.exists():
            raise RuntimeError(f"Config file not created: {conf_file}")

        config_content = conf_file.read_text(encoding="utf-8", errors="replace")

        private_key = self._extract(config_content, "PrivateKey")
        allowed_ip_from_conf = self._extract(config_content, "Address").split("/")[0]
        allowed_ip = allowed_ip_from_stdout or allowed_ip_from_conf
        if not public_key:
            raise RuntimeError(
                "Could not get client public key. Update add-wg-client.sh: script must echo WG_CLIENT_PUBLIC_KEY=..."
            )

        return {
            "allowed_ip": allowed_ip,
            "private_key": private_key,
            "public_key": public_key,
            "config_content": config_content,
            "conf_path": str(conf_file),
        }

    def _parse_stdout_key(self, stdout: str, key: str) -> str:
        """Из вывода скрипта извлечь значение KEY=value (одна строка)."""
        prefix = key + "="
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return ""

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
        """Мок для локального теста без WireGuard: ключи в формате WG, чтобы QR/импорт не отклонялись."""
        import base64
        import zlib

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        def _b64_32(b: bytes) -> str:
            return base64.b64encode(b).decode("ascii")

        client_priv = X25519PrivateKey.generate()
        client_priv_bytes = client_priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        client_pub_bytes = client_priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        # Отдельная пара только чтобы [Peer] PublicKey был валидной строкой ключа (не реальный сервер).
        server_pub_bytes = X25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        base = "10.66.0"
        h = zlib.crc32(client_name.encode("utf-8")) & 0xFFFFFFFF
        allowed_ip = f"{base}.{2 + (h % 253)}"

        private_key = _b64_32(client_priv_bytes)
        public_key = _b64_32(client_pub_bytes)
        server_peer_key = _b64_32(server_pub_bytes)

        config_content = f"""[Interface]
PrivateKey = {private_key}
Address = {allowed_ip}/32
DNS = 1.1.1.1, 1.0.0.1

[Peer]
PublicKey = {server_peer_key}
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

        wg_prefix = ["sudo"] if self.use_sudo else []
        proc = await asyncio.create_subprocess_exec(
            *wg_prefix, "wg", "syncconf", "wg0", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        strip_proc = await asyncio.create_subprocess_exec(
            *wg_prefix, "wg-quick", "strip", "wg0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        strip_out, _ = await strip_proc.communicate()
        await proc.communicate(input=strip_out)

    def delete_client_conf_file(self, client_name: str) -> None:
        """Удаляет файл userX_Y.conf из каталога клиентов (если есть)."""
        if not client_name:
            return
        path = self.clients_dir / f"{client_name}.conf"
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            print(f"[WG] delete_client_conf_file failed: {e}", flush=True)

    async def restore_client(self, public_key: str, allowed_ip: str) -> None:
        """
        Восстанавливает peer в wg0.conf (после разблокировки админом).
        Добавляет блок [Peer] с PublicKey и AllowedIPs и применяет конфиг.
        """
        if not self.conf_path or not Path(self.conf_path).exists():
            return  # мок: ничего не делаем
        path = Path(self.conf_path)
        allowed = allowed_ip.strip()
        if allowed and "/" not in allowed:
            allowed = f"{allowed}/32"
        peer_block = f"""
[Peer]
# restored
PublicKey = {public_key}
AllowedIPs = {allowed}
"""
        text = path.read_text(encoding="utf-8", errors="replace")
        if public_key in text:
            return  # уже есть (например, не удалялся)
        path.write_text(text.rstrip() + "\n" + peer_block.lstrip(), encoding="utf-8")
        wg_prefix = ["sudo"] if self.use_sudo else []
        strip_proc = await asyncio.create_subprocess_exec(
            *wg_prefix, "wg-quick", "strip", "wg0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        strip_out, _ = await strip_proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            *wg_prefix, "wg", "syncconf", "wg0", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=strip_out)


wireguard_service = WireGuardService()
