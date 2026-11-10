import json
import hmac
import queue
import secrets
import socket
import string
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk


PORT = 1010
GAME_CODE_CHARACTERS = string.ascii_uppercase + string.digits
GAME_CODE_LENGTH = 4


def get_local_network_addresses():
    return sorted(
        {
            result[4][0]
            for result in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
            )
            if not result[4][0].startswith(("127.", "169.254."))
        }
    )


class server:
    def __init__(self, host="0.0.0.0", port=PORT):
        self.host = host
        self.port = port
        self.games = {}
        self._games_lock = threading.Lock()
        self._accounts_lock = threading.Lock()
        self._sessions_lock = threading.Lock()
        self._sessions = {}
        self.accounts_path = Path(__file__).with_name("accounts.json")
        self._stop_event = threading.Event()

    def start(self, events):
        self._stop_event.clear()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.settimeout(0.25)
            listener.bind((self.host, self.port))
            listener.listen()
            try:
                addresses = get_local_network_addresses()
            except OSError as error:
                events.put(("server_started", self.port, (), str(error)))
            else:
                events.put(("server_started", self.port, addresses, None))

            while not self._stop_event.is_set():
                try:
                    connection, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise

                threading.Thread(
                    target=self.handle_connection,
                    args=(connection, address, events),
                    daemon=True,
                ).start()

        events.put(("server_stopped",))

    def handle_connection(self, connection, address, events):
        with connection:
            try:
                with connection.makefile("r", encoding="utf-8") as reader:
                    request_line = reader.readline()
                request = json.loads(request_line)
                response = self.handle_request(request)
            except json.JSONDecodeError:
                response = self.error_response("Invalid request.")
            except (OSError, UnicodeDecodeError, ValueError) as error:
                response = self.error_response(f"Server error: {error}")
                events.put(("client_error", str(error), address[0]))

            try:
                connection.sendall((json.dumps(response) + "\n").encode("utf-8"))
            except OSError as error:
                events.put(("client_error", str(error), address[0]))

    def handle_request(self, request):
        if not isinstance(request, dict):
            return self.error_response("Invalid request.")

        action = request.get("action")
        if action in ("register", "login"):
            return self.handle_auth(action, request)
        if action == "logout":
            token = request.get("token")
            username = self.authenticated_username(token)
            player_id = request.get("player_id")
            if username is None or not self.is_valid_player_id(player_id):
                return self.error_response("You are not logged in.")
            self.remove_player_from_games(player_id, username)
            with self._sessions_lock:
                self._sessions.pop(token, None)
            return {"ok": True}

        if action in ("check_session", "leave"):
            token = request.get("token")
            username = self.authenticated_username(token)
            if username is None:
                return self.error_response("Please log in first.")
            if action == "check_session":
                return {"ok": True}

            player_id = request.get("player_id")
            if not self.is_valid_player_id(player_id):
                return self.error_response("Invalid player window ID.")
            self.remove_player_from_games(player_id, username)
            return {"ok": True}

        username = self.authenticated_username(request.get("token"))
        if username is None:
            return self.error_response("Please log in first.")

        if action in ("create", "join", "players"):
            player_id = request.get("player_id")
            if not self.is_valid_player_id(player_id):
                return self.error_response("Invalid player window ID.")

            if action == "create":
                with self._games_lock:
                    game_id = self.new_game_id()
                    self.games[game_id] = {player_id: username}
                    players = self.format_players(self.games[game_id])
                return {"ok": True, "game_id": game_id, "players": players}

            game_id = request.get("game_id")
            if not isinstance(game_id, str):
                return self.error_response("Enter a valid four-character game code.")
            game_id = game_id.strip().upper()
            if not self.is_valid_game_id(game_id):
                return self.error_response("Enter a valid four-character game code.")

            with self._games_lock:
                players = self.games.get(game_id)
                if players is None:
                    return self.error_response("No game exists with that code.")
                if action == "join":
                    players[player_id] = username
                elif player_id not in players:
                    return self.error_response("Join the game before viewing it.")
                return {
                    "ok": True,
                    "game_id": game_id,
                    "players": self.format_players(players),
                }

        return self.error_response("Unknown request.")

    def remove_player_from_games(self, player_id, username):
        with self._games_lock:
            empty_games = []
            for game_id, players in self.games.items():
                if players.get(player_id) == username:
                    players.pop(player_id)
                if not players:
                    empty_games.append(game_id)
            for game_id in empty_games:
                self.games.pop(game_id)

    def handle_auth(self, action, request):
        username = request.get("username")
        password = request.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return self.error_response("Enter a username and password.")
        username = username.strip()
        if not 3 <= len(username) <= 24 or not all(
            character.isalnum() or character in "_-" for character in username
        ):
            return self.error_response(
                "Usernames must be 3-24 letters, numbers, underscores, or hyphens."
            )
        if not 4 <= len(password) <= 128:
            return self.error_response("Passwords must be between 4 and 128 characters.")

        username_key = username.casefold()
        try:
            with self._accounts_lock:
                accounts = self.load_accounts()
                if action == "register":
                    if username_key in accounts:
                        return self.error_response("That username is already taken.")
                    accounts[username_key] = {
                        "username": username,
                        "password": password,
                    }
                    self.save_accounts(accounts)
                    return self.create_session(username)

                account = accounts.get(username_key)
                if account is None or not hmac.compare_digest(
                    account.get("password", ""), password
                ):
                    return self.error_response("Incorrect username or password.")
                return self.create_session(account["username"])
        except (OSError, ValueError, TypeError) as error:
            return self.error_response(f"Could not access accounts.json: {error}")

    def load_accounts(self):
        if not self.accounts_path.exists():
            return {}
        data = json.loads(self.accounts_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
            raise ValueError("the file must contain an 'accounts' object")
        accounts = data["accounts"]
        for account in accounts.values():
            if (
                not isinstance(account, dict)
                or not isinstance(account.get("username"), str)
                or not isinstance(account.get("password"), str)
            ):
                raise ValueError("each account must have a username and password")
        return accounts

    def save_accounts(self, accounts):
        temporary_path = self.accounts_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps({"accounts": accounts}, indent=2), encoding="utf-8"
        )
        temporary_path.replace(self.accounts_path)

    def create_session(self, username):
        with self._sessions_lock:
            username_key = username.casefold()
            if any(
                active_username.casefold() == username_key
                for active_username in self._sessions.values()
            ):
                return self.error_response("This account is already logged in.")
            token = secrets.token_urlsafe(32)
            self._sessions[token] = username
        return {"ok": True, "token": token, "username": username}

    def authenticated_username(self, token):
        if not isinstance(token, str):
            return None
        with self._sessions_lock:
            return self._sessions.get(token)

    def new_game_id(self):
        while True:
            game_id = "".join(
                secrets.choice(GAME_CODE_CHARACTERS)
                for _ in range(GAME_CODE_LENGTH)
            )
            if game_id not in self.games:
                return game_id

    @staticmethod
    def is_valid_game_id(game_id):
        return len(game_id) == GAME_CODE_LENGTH and all(
            character in GAME_CODE_CHARACTERS for character in game_id
        )

    @staticmethod
    def is_valid_player_id(player_id):
        return (
            isinstance(player_id, str)
            and len(player_id) == 32
            and all(character in string.hexdigits for character in player_id)
        )

    @staticmethod
    def format_players(players):
        return [
            {"player_id": player_id, "username": username}
            for player_id, username in players.items()
        ]

    @staticmethod
    def error_response(message):
        return {"ok": False, "error": message}

    def stop(self):
        self._stop_event.set()


class server_interface:
    def __init__(self, root):
        self.root = root
        self.root.title("MathShips Server")
        self.root.resizable(False, False)
        self.events = queue.Queue()
        self.server_instance = None
        self.server_thread = None

        container = ttk.Frame(root, padding=16)
        container.grid(sticky="nsew")
        ttk.Label(
            container,
            text=f"Game server — TCP port {PORT}",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.start_button = ttk.Button(
            container, text="Start server", command=self.start_server
        )
        self.start_button.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.stop_button = ttk.Button(
            container, text="Stop server", command=self.stop_server, state="disabled"
        )
        self.stop_button.grid(row=1, column=1, sticky="ew", padx=(4, 0))

        self.status = tk.StringVar(value="Server stopped.")
        ttk.Label(container, textvariable=self.status, wraplength=360).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=12
        )
        ttk.Label(
            container,
            text=(
                "Toy app only: accounts are stored as plain text in accounts.json "
                "and passwords travel over plain TCP. Use game-only passwords."
            ),
            wraplength=360,
        ).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(
            container,
            text=f"Account file: {Path(__file__).with_name('accounts.json')}",
            wraplength=360,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.process_events)

    def start_server(self):
        if self.server_thread and self.server_thread.is_alive():
            return
        self.server_instance = server()
        self.server_thread = threading.Thread(
            target=self.run_server, args=(self.server_instance,), daemon=True
        )
        self.server_thread.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set(f"Starting server on port {PORT}...")

    def run_server(self, instance):
        try:
            instance.start(self.events)
        except (OSError, ValueError) as error:
            self.events.put(("server_error", f"Could not run server: {error}"))

    def stop_server(self):
        if self.server_instance:
            self.server_instance.stop()
        self.stop_button.configure(state="disabled")
        self.status.set("Stopping server...")

    def process_events(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            if event[0] == "server_started":
                if event[2]:
                    addresses = ", ".join(
                        f"{address}:{event[1]}" for address in event[2]
                    )
                    self.status.set(f"Listening for local network clients at {addresses}")
                else:
                    self.status.set(
                        "Listening on all interfaces, but the local network address "
                        f"could not be determined ({event[3]})."
                    )
            elif event[0] == "server_stopped":
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.status.set("Server stopped.")
            elif event[0] == "server_error":
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.status.set(event[1])
            elif event[0] == "client_error":
                self.status.set(f"Request from {event[2]} failed: {event[1]}")

        self.root.after(100, self.process_events)

    def close(self):
        if self.server_instance:
            self.server_instance.stop()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    server_interface(window)
    window.mainloop()




"""
AI DO NOT TOUCH THIS BLOCK OF CODE

& 'd:\Fbamse\Project\VCTGames\.venv\Scripts\python.exe'

cd "D:\Fbamse\Project\VCTGames\sample_apps\MathShips"



cd "D:\Fbamse\Project\VCTGames\sample_apps\MathShips"
& 'd:\Fbamse\Project\VCTGames\.venv\Scripts\python.exe' server.py


cd "D:\Fbamse\Project\VCTGames\sample_apps\MathShips"
& 'd:\Fbamse\Project\VCTGames\.venv\Scripts\python.exe' client.py


"""
