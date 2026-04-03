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
        self.wg_interface = (getattr(settings, "wg_interface", None) or "wg0").strip() or "wg0"
        self._helper_override = (getattr(settings, "wg_helper_script_path", None) or "").strip()

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

    def _resolved_helper_script(self) -> str:
        if self._helper_override:
            p = Path(self._helper_override)
            return str(p) if p.is_file() else ""
        if self.script_path:
            s = Path(self.script_path).resolve().parent / "wg-backend-helper.sh"
            if s.is_file():
                return str(s)
        return ""

    async def _invoke_helper(self, *args: str) -> tuple[int, str]:
        """
        Важно: вызываем «sudo /path/wg-backend-helper.sh …», без «sudo env …».
        Иначе sudo сопоставляет whitelist с командой env, а не со скриптом — NOPASSWD не срабатывает.
        """
        hpath = self._resolved_helper_script()
        if not hpath:
            return -1, "helper script not found"
        cmd = (["sudo"] if self.use_sudo else []) + [hpath, *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        combined = (
            out.decode("utf-8", errors="replace") + "\n" + err.decode("utf-8", errors="replace")
        ).strip()
        return proc.returncode, combined

    def _wg_prefix(self) -> list[str]:
        return ["sudo"] if self.use_sudo else []

    async def _wg_set_peer_remove(self, pubkey: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *self._wg_prefix(),
            "wg",
            "set",
            self.wg_interface,
            "peer",
            pubkey,
            "remove",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            print(
                f"[WG] wg set {self.wg_interface} peer remove (non-fatal if peer absent): "
                f"{err.decode('utf-8', errors='replace')}",
                flush=True,
            )

    async def _read_main_conf(self) -> str | None:
        path = Path(self.conf_path)
        if self.use_sudo:
            proc = await asyncio.create_subprocess_exec(
                "sudo",
                "cat",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            if proc.returncode != 0:
                print(
                    f"[WG] sudo cat {path} failed ({proc.returncode}): "
                    f"{err.decode('utf-8', errors='replace')}",
                    flush=True,
                )
                return None
            return out.decode("utf-8", errors="replace")
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[WG] read {path}: {e}", flush=True)
            return None

    async def _write_main_conf(self, content: str) -> bool:
        path = Path(self.conf_path)
        if self.use_sudo:
            proc = await asyncio.create_subprocess_exec(
                "sudo",
                "tee",
                str(path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate(input=content.encode("utf-8"))
            if proc.returncode != 0:
                print(
                    f"[WG] sudo tee {path} failed: {err.decode('utf-8', errors='replace')}",
                    flush=True,
                )
                return False
            return True
        try:
            path.write_text(content, encoding="utf-8")
            return True
        except OSError as e:
            print(f"[WG] write {path}: {e}", flush=True)
            return False

    @staticmethod
    def _strip_peer_blocks_with_pubkey(text: str, pubkey: str) -> str:
        pk = pubkey.strip()
        lines = text.splitlines()
        out: list[str] = []
        i = 0
        while i < len(lines):
            if lines[i].strip() == "[Peer]":
                block = [lines[i]]
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("["):
                    block.append(lines[i])
                    i += 1
                block_pk: str | None = None
                for ln in block:
                    s = ln.strip()
                    if s.startswith("PublicKey"):
                        _, _, rest = s.partition("=")
                        block_pk = rest.strip()
                        break
                if block_pk != pk:
                    out.extend(block)
            else:
                out.append(lines[i])
                i += 1
        result = "\n".join(out)
        if text.endswith("\n") and result and not result.endswith("\n"):
            result += "\n"
        return result

    @staticmethod
    def _main_conf_has_peer_pubkey(text: str, pubkey: str) -> bool:
        pk = pubkey.strip()
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if lines[i].strip() == "[Peer]":
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("["):
                    s = lines[i].strip()
                    if s.startswith("PublicKey"):
                        _, _, rest = s.partition("=")
                        if rest.strip() == pk:
                            return True
                    i += 1
            else:
                i += 1
        return False

    async def _apply_syncconf(self) -> bool:
        wg_prefix = self._wg_prefix()
        strip_proc = await asyncio.create_subprocess_exec(
            *wg_prefix,
            "wg-quick",
            "strip",
            self.wg_interface,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        strip_out, strip_err = await strip_proc.communicate()
        if strip_proc.returncode != 0:
            print(
                f"[WG] wg-quick strip {self.wg_interface} failed: "
                f"{strip_err.decode('utf-8', errors='replace')}",
                flush=True,
            )
            return False
        proc = await asyncio.create_subprocess_exec(
            *wg_prefix,
            "wg",
            "syncconf",
            self.wg_interface,
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(input=strip_out)
        if proc.returncode != 0:
            print(
                f"[WG] wg syncconf {self.wg_interface} failed: "
                f"{err.decode('utf-8', errors='replace')}",
                flush=True,
            )
            return False
        return True

    async def revoke_client(self, public_key: str) -> None:
        """
        Снимает peer с интерфейса (wg set … remove), правит wg*.conf на диске и syncconf.
        При WG_USE_SUDO и недоступном wg0.conf процессу — используется sudo cat/tee или wg-backend-helper.sh.
        """
        if not (self.conf_path or "").strip():
            return
        pk = (public_key or "").strip()
        if not pk:
            print("[WG] revoke_client: empty public key", flush=True)
            return
        path = Path(self.conf_path)
        if self._resolved_helper_script():
            code, msg = await self._invoke_helper("revoke-peer", pk, self.conf_path, self.wg_interface)
            if code != 0:
                print(f"[WG] helper revoke-peer failed ({code}): {msg}", flush=True)
            return

        if not self.use_sudo and not path.is_file():
            print("[WG] revoke_client: wg conf not found (mock?)", flush=True)
            return

        await self._wg_set_peer_remove(pk)
        text = await self._read_main_conf()
        if text is None:
            print(
                "[WG] revoke_client: cannot read wg conf — peer dropped from runtime only until next wg-quick restart; "
                "install wg-backend-helper.sh or add sudoers for: sudo cat/tee "
                f"{self.conf_path}",
                flush=True,
            )
            return
        new_text = self._strip_peer_blocks_with_pubkey(text, pk)
        if new_text == text:
            print(
                f"[WG] revoke_client: no [Peer] with matching PublicKey (DB key prefix {pk[:12]}…); "
                "check wg0.conf vs DB",
                flush=True,
            )
        if not await self._write_main_conf(new_text):
            return
        await self._apply_syncconf()

    async def delete_client_conf_file(self, client_name: str) -> None:
        """Удаляет userX_Y.conf в каталоге клиентов (sudo rm при WG_USE_SUDO)."""
        if not client_name or not re.fullmatch(r"[a-zA-Z0-9_.-]+", client_name):
            print(f"[WG] delete_client_conf_file: invalid name {client_name!r}", flush=True)
            return
        path = self.clients_dir / f"{client_name}.conf"
        if self._resolved_helper_script():
            code, msg = await self._invoke_helper("rm-client-conf", client_name, str(self.clients_dir))
            if code != 0:
                print(f"[WG] helper rm-client-conf failed ({code}): {msg}", flush=True)
            return
        if self.use_sudo:
            proc = await asyncio.create_subprocess_exec(
                "sudo",
                "rm",
                "-f",
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                print(
                    f"[WG] sudo rm client conf failed: {err.decode('utf-8', errors='replace')}",
                    flush=True,
                )
            return
        try:
            if path.is_file():
                path.unlink()
        except OSError as e:
            print(f"[WG] delete_client_conf_file failed: {e}", flush=True)

    async def restore_client(self, public_key: str, allowed_ip: str) -> None:
        """
        Восстанавливает peer в wg*.conf (после разблокировки админом) и применяет syncconf.
        """
        if not (self.conf_path or "").strip():
            return
        pk = (public_key or "").strip()
        if not pk:
            return
        path = Path(self.conf_path)
        allowed = allowed_ip.strip()
        if allowed and "/" not in allowed:
            allowed = f"{allowed}/32"

        if self._resolved_helper_script():
            code, msg = await self._invoke_helper("append-peer", pk, allowed, self.conf_path, self.wg_interface)
            if code != 0:
                print(f"[WG] helper append-peer failed ({code}): {msg}", flush=True)
            return

        if not self.use_sudo and not path.is_file():
            return
        text = await self._read_main_conf()
        if text is None:
            print("[WG] restore_client: cannot read wg conf", flush=True)
            return
        if self._main_conf_has_peer_pubkey(text, pk):
            return
        peer_block = (
            "\n[Peer]\n"
            "# restored\n"
            f"PublicKey = {pk}\n"
            f"AllowedIPs = {allowed}\n"
        )
        if not await self._write_main_conf(text.rstrip() + peer_block):
            return
        await self._apply_syncconf()


wireguard_service = WireGuardService()
