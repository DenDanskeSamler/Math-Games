import json
import queue
import socket
import threading
import tkinter as tk
import uuid
from tkinter import ttk


PORT = 1010
SERVER_HOST = "192.168.75.202"
GAME_CODE_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_CHAT_MESSAGE_LENGTH = 500


class network_client:
    def __init__(self, host=SERVER_HOST, port=PORT, player_id=None):
        self.host = host
        self.port = port
        self.player_id = player_id or uuid.uuid4().hex.upper()
        self.token = None
        self.username = None

    def register(self, username, password):
        return self.authenticate("register", username, password)

    def login(self, username, password):
        return self.authenticate("login", username, password)

    def authenticate(self, action, username, password):
        response = self.request(
            {"action": action, "username": username, "password": password}
        )
        self.token = response["token"]
        self.username = response["username"]
        return response

    def logout(self):
        response = self.request(
            {
                "action": "logout",
                "token": self.token,
                "player_id": self.player_id,
            }
        )
        self.token = None
        self.username = None
        return response

    def check_session(self):
        return self.request({"action": "check_session", "token": self.token})

    def leave_game(self):
        return self.request(
            {
                "action": "leave",
                "token": self.token,
                "player_id": self.player_id,
            }
        )

    def create_game(self):
        return self.request(
            {"action": "create", "token": self.token, "player_id": self.player_id}
        )

    def join_game(self, game_id):
        return self.request(
            {
                "action": "join",
                "game_id": game_id,
                "token": self.token,
                "player_id": self.player_id,
            }
        )

    def get_players(self, game_id):
        return self.request(
            {
                "action": "players",
                "game_id": game_id,
                "token": self.token,
                "player_id": self.player_id,
            }
        )

    def send_chat(self, game_id, message):
        return self.request(
            {
                "action": "send_chat",
                "game_id": game_id,
                "message": message,
                "token": self.token,
                "player_id": self.player_id,
            }
        )

    def request(self, request):
        with socket.create_connection((self.host, self.port), timeout=5) as connection:
            connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
            with connection.makefile("r", encoding="utf-8") as reader:
                response_line = reader.readline()

        if not response_line:
            raise ConnectionError("The server closed the connection without responding")
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as error:
            raise ConnectionError("The server returned an invalid response") from error
        if not isinstance(response, dict):
            raise ConnectionError("The server returned an invalid response")
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "The request failed."))
        return response


class client_interface:
    def __init__(self, root):
        self.root = root
        self.root.title("MathShips Login")
        self.root.geometry("390x330")
        self.root.resizable(False, False)
        self.events = queue.Queue()
        self.player_id = uuid.uuid4().hex.upper()
        self.api = None
        self.current_game_id = None
        self.refresh_in_flight = False
        self.menu_frame = None
        self.client_frame = None
        self.refresh_after_id = None
        self.closing = False
        self.logout_in_flight = False

        container = ttk.Frame(root, padding=16)
        self.container = container
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        self.title_label = ttk.Label(
            container, text="MathShips Login", font=("Segoe UI", 12, "bold")
        )
        self.title_label.grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.status = tk.StringVar(value=f"Connect to a server on port {PORT}.")
        self.status_label = ttk.Label(
            container, textvariable=self.status, wraplength=360
        )
        self.status_label.grid(row=1, column=0, sticky="w", pady=(0, 8))

        self.login_frame = ttk.Frame(container)
        self.login_frame.grid(row=2, column=0, sticky="ew")
        self.login_frame.columnconfigure(1, weight=1)

        ttk.Label(self.login_frame, text="Server address:").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.host_entry = ttk.Entry(self.login_frame, width=28)
        self.host_entry.insert(0, SERVER_HOST)
        self.host_entry.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(self.login_frame, text="Username:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.username_entry = ttk.Entry(self.login_frame, width=28)
        self.username_entry.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(self.login_frame, text="Password:").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.password_entry = ttk.Entry(self.login_frame, width=28, show="*")
        self.password_entry.grid(row=2, column=1, sticky="ew", pady=4)

        self.login_button = ttk.Button(
            self.login_frame, text="Log in", command=self.login
        )
        self.login_button.grid(row=3, column=0, sticky="ew", padx=(0, 4), pady=8)
        self.register_button = ttk.Button(
            self.login_frame, text="Create account", command=self.register
        )
        self.register_button.grid(row=3, column=1, sticky="ew", padx=(4, 0), pady=8)
        ttk.Label(
            self.login_frame,
            text=(
                "Toy app only: passwords are stored as plain text on the server "
                "and sent over plain TCP. Do not reuse a real password."
            ),
            wraplength=360,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.process_events)

    def login(self):
        self.authenticate("login")

    def register(self):
        self.authenticate("register")

    def authenticate(self, action):
        host = self.host_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        if not host or not username or not password:
            self.status.set("Enter the server address, username, and password.")
            return
        if action == "register" and len(password) < 4:
            self.status.set("Passwords must be at least four characters.")
            return

        self.set_auth_buttons("disabled")
        self.status.set("Creating account..." if action == "register" else "Logging in...")
        threading.Thread(
            target=self.run_authentication,
            args=(action, host, username, password),
            daemon=True,
        ).start()

    def run_authentication(self, action, host, username, password):
        api = network_client(host=host, player_id=self.player_id)
        try:
            if action == "register":
                api.register(username, password)
            else:
                api.login(username, password)
        except (OSError, RuntimeError) as error:
            self.events.put(("auth_error", str(error)))
        else:
            self.events.put(("auth_success", api))

    def set_auth_buttons(self, state):
        self.login_button.configure(state=state)
        self.register_button.configure(state=state)

    def open_main_menu(self):
        self.login_frame.grid_remove()
        if self.menu_frame:
            self.menu_frame.destroy()
            self.menu_frame = None
        if self.client_frame:
            self.client_frame.destroy()
            self.client_frame = None
        self.root.title("MathShips Main Menu")
        self.root.geometry("520x410")
        self.root.minsize(480, 390)
        self.root.resizable(False, False)
        self.status_label.configure(wraplength=480)
        self.title_label.configure(text="MathShips")

        self.menu_frame = ttk.Frame(self.container)
        self.menu_frame.grid(row=2, column=0, sticky="nsew")
        self.menu_frame.columnconfigure(0, weight=1)

        header = ttk.Frame(self.menu_frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)
        self.username_label = ttk.Label(
            header,
            text=self.api.username,
            font=("Segoe UI", 16, "bold"),
        )
        self.username_label.grid(row=0, column=0, sticky="w")
        self.logout_button = ttk.Button(
            header, text="Log out", command=self.logout
        )
        self.logout_button.grid(row=0, column=1, sticky="e", padx=(12, 0))

        create_card = ttk.LabelFrame(
            self.menu_frame, text="Create a game", padding=14
        )
        create_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        create_card.columnconfigure(0, weight=1)
        self.create_button = ttk.Button(
            create_card, text="Create game", command=self.create_game
        )
        self.create_button.grid(row=0, column=0, sticky="ew")

        join_card = ttk.LabelFrame(
            self.menu_frame, text="Join a game", padding=14
        )
        join_card.grid(row=2, column=0, sticky="ew")
        join_card.columnconfigure(0, weight=1)
        self.join_code = tk.StringVar()
        self.join_entry = ttk.Entry(
            join_card, textvariable=self.join_code, width=10, font=("Segoe UI", 12)
        )
        self.join_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.join_button = ttk.Button(
            join_card, text="Join game", command=self.join_game
        )
        self.join_button.grid(row=0, column=1, sticky="ew")
        self.join_entry.bind("<Return>", lambda _event: self.join_button.invoke())

        if self.refresh_after_id is None:
            self.refresh_after_id = self.root.after(2000, self.refresh_players)

    def open_client_page(self):
        if self.menu_frame:
            self.menu_frame.destroy()
            self.menu_frame = None
        self.root.title("MathShips Game")
        self.root.geometry("760x600")
        self.root.minsize(640, 480)
        self.root.resizable(True, True)
        self.status_label.configure(wraplength=700)
        self.title_label.configure(text="MathShips")

        self.client_frame = ttk.Frame(self.container)
        self.client_frame.grid(row=2, column=0, sticky="nsew")
        self.client_frame.columnconfigure(0, weight=1)
        self.client_frame.rowconfigure(2, weight=1)

        ttk.Label(
            self.client_frame,
            text=f"Client window ID: {self.player_id}",
            wraplength=390,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        code_frame = ttk.Frame(self.client_frame)
        code_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        code_frame.columnconfigure(1, weight=1)
        ttk.Label(code_frame, text="Game code:").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.game_code = tk.StringVar()
        self.game_code_entry = ttk.Entry(
            code_frame, textvariable=self.game_code, width=7, state="readonly"
        )
        self.game_code_entry.grid(row=0, column=1, sticky="w")

        game_body = ttk.Frame(self.client_frame)
        game_body.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        game_body.columnconfigure(0, weight=1)
        game_body.columnconfigure(1, weight=3)
        game_body.rowconfigure(0, weight=1)

        players_panel = ttk.LabelFrame(game_body, text="Players", padding=8)
        players_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        players_panel.columnconfigure(0, weight=1)
        players_panel.rowconfigure(0, weight=1)
        self.player_list = tk.Listbox(players_panel, height=12)
        self.player_list.grid(row=0, column=0, sticky="nsew")

        chat_panel = ttk.LabelFrame(game_body, text="Game chat", padding=8)
        chat_panel.grid(row=0, column=1, sticky="nsew")
        chat_panel.columnconfigure(0, weight=1)
        chat_panel.rowconfigure(0, weight=1)
        self.chat_display = tk.Text(
            chat_panel, height=16, wrap="word", state="disabled"
        )
        self.chat_display.grid(row=0, column=0, sticky="nsew")
        chat_scrollbar = ttk.Scrollbar(
            chat_panel, orient="vertical", command=self.chat_display.yview
        )
        chat_scrollbar.grid(row=0, column=1, sticky="ns")
        self.chat_display.configure(yscrollcommand=chat_scrollbar.set)
        self.last_chat_message_id = 0

        chat_input = ttk.Frame(chat_panel)
        chat_input.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        chat_input.columnconfigure(0, weight=1)
        self.chat_entry = ttk.Entry(chat_input)
        self.chat_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.chat_send_button = ttk.Button(
            chat_input, text="Send", command=self.send_chat
        )
        self.chat_send_button.grid(row=0, column=1, sticky="e")
        self.chat_entry.bind("<Return>", lambda _event: self.send_chat())

        self.quit_button = ttk.Button(
            self.client_frame,
            text="Quit to main menu",
            command=self.quit_to_main_menu,
        )
        self.quit_button.grid(row=3, column=0, sticky="ew")

    def create_game(self):
        self.start_game_request("create")

    def join_game(self):
        game_id = self.join_code.get().strip().upper()
        if len(game_id) != 4 or any(
            character not in GAME_CODE_CHARACTERS for character in game_id
        ):
            self.status.set("Game codes must be four letters or numbers.")
            return
        self.start_game_request("join", game_id)

    def send_chat(self):
        message = self.chat_entry.get().strip()
        if not message:
            return
        if len(message) > MAX_CHAT_MESSAGE_LENGTH:
            self.status.set(
                f"Chat messages can be at most {MAX_CHAT_MESSAGE_LENGTH} characters."
            )
            return
        if not self.api or not self.current_game_id:
            return
        self.chat_entry.configure(state="disabled")
        self.chat_send_button.configure(state="disabled")
        threading.Thread(
            target=self.run_send_chat,
            args=(self.api, self.current_game_id, message),
            daemon=True,
        ).start()

    def run_send_chat(self, api, game_id, message):
        try:
            response = api.send_chat(game_id, message)
        except OSError as error:
            self.events.put(("server_unavailable", str(error)))
        except RuntimeError as error:
            self.events.put(("chat_error", game_id, str(error)))
        else:
            self.events.put(("chat_sent", game_id, response["messages"]))

    def start_game_request(self, action, game_id=None):
        self.create_button.configure(state="disabled")
        self.join_button.configure(state="disabled")
        self.logout_button.configure(state="disabled")
        self.status.set("Creating game..." if action == "create" else "Joining game...")
        threading.Thread(
            target=self.run_game_request,
            args=(self.api, action, game_id),
            daemon=True,
        ).start()

    def run_game_request(self, api, action, game_id):
        try:
            if action == "create":
                response = api.create_game()
            else:
                response = api.join_game(game_id)
        except OSError as error:
            self.events.put(("server_unavailable", str(error)))
        except RuntimeError as error:
            self.events.put(("game_error", str(error)))
        else:
            self.events.put(("game_ready", action, response))

    def refresh_players(self):
        self.refresh_after_id = None
        if not self.api:
            return
        if not self.refresh_in_flight:
            self.refresh_in_flight = True
            if self.current_game_id:
                threading.Thread(
                    target=self.run_player_refresh,
                    args=(self.api, self.current_game_id),
                    daemon=True,
                ).start()
            else:
                threading.Thread(
                    target=self.run_session_check,
                    args=(self.api,),
                    daemon=True,
                ).start()
        self.refresh_after_id = self.root.after(2000, self.refresh_players)

    def run_player_refresh(self, api, game_id):
        try:
            response = api.get_players(game_id)
        except OSError as error:
            self.events.put(("server_unavailable", str(error)))
        except RuntimeError as error:
            self.events.put(("players_error", game_id, str(error)))
        else:
            self.events.put(
                (
                    "players_updated",
                    game_id,
                    response["players"],
                    response["messages"],
                )
            )

    def run_session_check(self, api):
        try:
            api.check_session()
        except OSError as error:
            self.events.put(("server_unavailable", str(error)))
        except RuntimeError as error:
            self.events.put(("session_expired", str(error)))
        else:
            self.events.put(("session_checked",))

    def quit_to_main_menu(self):
        api = self.api
        if not api:
            return
        self.status.set("Returning to main menu...")
        self.current_game_id = None
        self.open_main_menu()
        self.create_button.configure(state="disabled")
        self.join_button.configure(state="disabled")
        self.logout_button.configure(state="disabled")
        threading.Thread(
            target=self.run_leave_game, args=(api,), daemon=True
        ).start()

    def run_leave_game(self, api):
        try:
            api.leave_game()
        except OSError as error:
            self.events.put(("server_unavailable", str(error)))
        except RuntimeError as error:
            self.events.put(("session_expired", str(error)))
        else:
            self.events.put(("leave_done",))

    def return_to_login(self, message):
        self.api = None
        self.current_game_id = None
        self.refresh_in_flight = False
        if self.refresh_after_id:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        for frame_name in ("menu_frame", "client_frame"):
            frame = getattr(self, frame_name)
            if frame:
                frame.destroy()
                setattr(self, frame_name, None)
        self.root.title("MathShips Login")
        self.root.minsize(1, 1)
        self.root.geometry("390x330")
        self.root.resizable(False, False)
        self.status_label.configure(wraplength=360)
        self.title_label.configure(text="MathShips Login")
        self.login_frame.grid(row=2, column=0, sticky="ew")
        self.password_entry.delete(0, "end")
        self.set_auth_buttons("normal")
        self.status.set(message)

    def logout(self):
        api = self.api
        if not api or self.logout_in_flight:
            return
        self.create_button.configure(state="disabled")
        self.join_button.configure(state="disabled")
        self.logout_button.configure(state="disabled")
        self.status.set("Logging out...")
        self.logout_in_flight = True
        threading.Thread(
            target=self.run_logout, args=(api,), daemon=True
        ).start()

    def run_logout(self, api):
        try:
            api.logout()
        except OSError as error:
            self.events.put(("server_unavailable", str(error)))
        except RuntimeError as error:
            self.events.put(("session_expired", str(error)))
        else:
            self.events.put(("logout_done",))

    def process_events(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            if self.closing:
                if event[0] in ("logout_done", "logout_error"):
                    self.logout_in_flight = False
                    self.root.destroy()
                    return
                continue

            if event[0] == "auth_success":
                self.api = event[1]
                self.status.set("Choose create or join a game.")
                self.password_entry.delete(0, "end")
                self.open_main_menu()
            elif event[0] == "auth_error":
                self.status.set(f"Login failed: {event[1]}")
                self.set_auth_buttons("normal")
            elif event[0] == "server_unavailable":
                self.return_to_login(
                    "Server connection lost. Log in again when it is available."
                )
            elif event[0] == "session_expired":
                self.return_to_login("Your session ended. Please log in again.")
            elif event[0] == "game_ready":
                action, response = event[1], event[2]
                if not self.menu_frame:
                    continue
                self.current_game_id = response["game_id"]
                self.open_client_page()
                self.game_code.set(self.current_game_id)
                self.update_players(response["players"])
                self.update_chat(response["messages"])
                action_text = "created" if action == "create" else "joined"
                self.status.set(f"Game {self.current_game_id} {action_text}.")
            elif event[0] == "game_error":
                if not self.menu_frame:
                    continue
                self.status.set(f"Game request failed: {event[1]}")
                self.create_button.configure(state="normal")
                self.join_button.configure(state="normal")
                self.logout_button.configure(state="normal")
            elif event[0] == "players_updated":
                self.refresh_in_flight = False
                if self.client_frame and event[1] == self.current_game_id:
                    self.update_players(event[2])
                    self.update_chat(event[3])
            elif event[0] == "players_error":
                self.refresh_in_flight = False
                if self.client_frame and event[1] == self.current_game_id:
                    self.current_game_id = None
                    self.open_main_menu()
                    self.status.set(
                        f"Game unavailable. Returned to main menu: {event[2]}"
                    )
            elif event[0] == "chat_sent":
                if self.client_frame and event[1] == self.current_game_id:
                    self.update_chat(event[2])
                    self.chat_entry.configure(state="normal")
                    self.chat_send_button.configure(state="normal")
                    self.chat_entry.delete(0, "end")
                    self.chat_entry.focus_set()
            elif event[0] == "chat_error":
                if self.client_frame and event[1] == self.current_game_id:
                    self.chat_entry.configure(state="normal")
                    self.chat_send_button.configure(state="normal")
                    self.status.set(f"Chat failed: {event[2]}")
            elif event[0] == "session_checked":
                self.refresh_in_flight = False
            elif event[0] == "leave_done":
                if self.menu_frame:
                    self.create_button.configure(state="normal")
                    self.join_button.configure(state="normal")
                    self.logout_button.configure(state="normal")
                    self.status.set("Returned to main menu.")
            elif event[0] == "logout_done":
                self.logout_in_flight = False
                self.return_to_login("Logged out.")
            elif event[0] == "logout_error":
                self.logout_in_flight = False
                if self.menu_frame:
                    self.create_button.configure(state="normal")
                    self.join_button.configure(state="normal")
                    self.logout_button.configure(state="normal")
                self.status.set(f"Logout failed: {event[1]}")

        self.root.after(100, self.process_events)

    def update_players(self, players):
        self.player_list.delete(0, "end")
        for player in players:
            self.player_list.insert(
                "end", f"{player['username']} ({player['player_id'][:8]})"
            )

    def update_chat(self, messages):
        if not messages or messages[-1]["id"] < self.last_chat_message_id:
            return
        self.last_chat_message_id = messages[-1]["id"]
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        for message in messages:
            self.chat_display.insert(
                "end", f"{message['username']}: {message['message']}\n"
            )
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def close(self):
        if self.closing:
            return
        self.closing = True
        api = self.api
        self.api = None
        if self.refresh_after_id:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        if self.logout_in_flight:
            return
        if api:
            self.status.set("Logging out before closing...")
            self.logout_in_flight = True
            threading.Thread(
                target=self.run_logout, args=(api,), daemon=True
            ).start()
        else:
            self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    client_interface(window)
    window.mainloop()
