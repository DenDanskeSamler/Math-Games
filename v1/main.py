import math
import queue
import sys
import time
import threading
import tkinter as tk
from pathlib import Path

import pygame as pg

if not __package__ and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from arcade_api import ApiRequestError, api_request
from session_store import (
    SessionStoreError,
    clear_session,
    load_session,
    save_session,
)
from lan_discovery import discover_server
from game_settings import SETTINGS
from ship_geometry import ShipGeometry
from arcade_worker import ArcadeWorker
from laser_effects import LaserEffects


DEV_MODE = "--dev" in sys.argv[1:]
network_server_url = None
network_token = None
network_username = None
network_game_id = None

screen_width = SETTINGS.screen_width
screen_height = SETTINGS.screen_height
side_margin = SETTINGS.side_margin
canvas_top = SETTINGS.canvas_top
ship_cell_size = SETTINGS.ship_cell_size
canvas_rect = pg.Rect(
    side_margin,
    canvas_top,
    screen_width - 2 * side_margin,
    screen_height - canvas_top - side_margin,
)
screen_rect = pg.Rect(0, 0, screen_width, screen_height)
ship_tray_rect = pg.Rect(
    canvas_rect.left,
    SETTINGS.ship_tray_top,
    canvas_rect.width,
    canvas_top - SETTINGS.ship_tray_top,
)
ship_lengths = SETTINGS.ship_lengths
ship_gap = SETTINGS.ship_gap
MOVE_POINT_RADIUS = SETTINGS.move_point_radius
ROTATE_WIDGET_RADIUS = SETTINGS.rotate_widget_radius
ship_total_width = len(ship_lengths) * ship_cell_size + ship_gap * (
    len(ship_lengths) - 1
)
tray_board_left = max(canvas_rect.left, ship_tray_rect.left)
tray_board_right = min(canvas_rect.right, ship_tray_rect.right)
ship_x = tray_board_left + (tray_board_right - tray_board_left - ship_total_width) // 2
ship_y = ship_tray_rect.top + SETTINGS.ship_tray_ship_offset
ships = []
for ship_length in ship_lengths:
    ships.append(
        pg.Rect(
            ship_x,
            ship_y,
            ship_cell_size,
            ship_length * ship_cell_size,
        )
    )
    ship_x += ship_cell_size + ship_gap
ships_left_dock = set()
ship_angles = {id(ship): 0.0 for ship in ships}
ships_locked = False
server_ships_locked = False
dragging_ship = None
rotating_ship = None
drag_offset = (0, 0)
last_rotate_pointer_angle = 0.0
rotate_degrees_remainder = 0.0

a = SETTINGS.initial_angle_radians
a_max = SETTINGS.max_angle_radians
b = SETTINGS.initial_height
b_max = canvas_rect.height

lazer_state = SETTINGS.laser_enabled
lazer_length = SETTINGS.laser_length
fire_button_fired = False
remote_player_state = None
network_game_status = None
last_shot_event = None
last_shot_until = 0.0
last_seen_shot_id = 0
multiplayer_ready = False
network_turn = False
fire_pending = False
fire_window_dismissed = False
own_hits = [[] for _ in ship_lengths]
network_actions = queue.Queue()
network_events = queue.Queue()
server_discovery_events = queue.Queue()
network_stop = threading.Event()
server_discovery_stop = threading.Event()
network_state_loaded = threading.Event()
network_state_lock = threading.Lock()
network_local_state = {}
network_state_initialized = False
laser_effects = LaserEffects(lazer_length, side_margin, canvas_rect.bottom)
ship_geometry = ShipGeometry(
    ships,
    ship_angles,
    ships_left_dock,
    ship_tray_rect,
    canvas_rect,
    MOVE_POINT_RADIUS,
    ROTATE_WIDGET_RADIUS,
)
pg.init()
screen = None
laser_overlay = None
ship_control_font = pg.font.Font(None, SETTINGS.ship_control_font_size)

def draw_lazerCannon(x, y, angle):
    # Draw a simple ship
    cannon_size = SETTINGS.laser_cannon_size
    points = [
        (
            x + cannon_size * math.cos(angle + math.pi / 4),
            y + cannon_size * math.sin(angle + math.pi / 4),
        ),
        (
            x + cannon_size * math.cos(angle + 3 * math.pi / 4),
            y + cannon_size * math.sin(angle + 3 * math.pi / 4),
        ),
        (
            x + cannon_size * math.cos(angle - 3 * math.pi / 4),
            y + cannon_size * math.sin(angle - 3 * math.pi / 4),
        ),
        (
            x + cannon_size * math.cos(angle - math.pi / 4),
            y + cannon_size * math.sin(angle - math.pi / 4),
        ),
    ]
    pg.draw.polygon(screen, (0, 0, 0), points)

def draw_lazer(x, y, angle, enabled, color):
    laser_effects.draw_beam(x, y, angle, enabled, color)

def fire_lazer():
    global fire_button_fired, fire_pending
    if not ship_geometry.all_ships_left_dock():
        return
    if not multiplayer_ready or not network_turn or fire_pending:
        return
    fire_button_fired = True
    laser_effects.start_pulse(-a, b)
    fire_button.config(bg="#00bcd4", activebackground="#00bcd4")
    fire_pending = True
    fire_button.config(state="disabled")
    if DEV_MODE:
        fire_pending = False
        fire_button.config(state="normal")
        game_status.set("Dev sandbox: laser pulse fired.")
        return
    network_actions.put("fire")

def toggle_lazer():
    global lazer_state
    lazer_state = not lazer_state
    lazer_button.config(text=f"Lazer: {'On' if lazer_state else 'Off'}")

def update_angle(*_):
    global a
    try:
        value = float(angle_value.get())
    except ValueError:
        return
    a = min(max(value, -a_max), a_max)

def update_height(*_):
    global b
    try:
        value = float(height_value.get())
    except ValueError:
        return
    b = min(max(value, 0), b_max)

def adjust_angle(amount):
    try:
        value = float(angle_value.get())
    except ValueError:
        value = a
    angle_value.set(str(round(min(max(value + amount, -a_max), a_max), 2)))

def adjust_height(amount):
    try:
        value = float(height_value.get())
    except ValueError:
        value = b
    height_value.set(str(round(min(max(value + amount, 0), b_max), 1)))

repeat_after_id = None

def repeat_adjustment(action):
    global repeat_after_id
    action()
    repeat_after_id = controls.after(
        SETTINGS.repeat_interval_ms, lambda: repeat_adjustment(action)
    )

def start_adjustment(_event, action):
    global repeat_after_id
    stop_adjustment()
    action()
    repeat_after_id = controls.after(
        SETTINGS.initial_repeat_delay_ms,
        lambda: repeat_adjustment(action),
    )
    return "break"

def stop_adjustment(_event=None):
    global repeat_after_id
    if repeat_after_id is not None:
        controls.after_cancel(repeat_after_id)
        repeat_after_id = None

def normalize_angle(_event=None):
    try:
        value = float(angle_value.get())
    except ValueError:
        value = a
    angle_value.set(str(round(min(max(value, -a_max), a_max), 2)))

def normalize_height(_event=None):
    try:
        value = float(height_value.get())
    except ValueError:
        value = b
    height_value.set(str(round(min(max(value, 0), b_max), 1)))

def valid_number(text):
    if text in ("", "-", "+", ".", "-.", "+."):
        return True
    try:
        return math.isfinite(float(text))
    except ValueError:
        return False

def current_game_snapshot():
    return {
        "angle": a,
        "height": b,
        "laser_enabled": lazer_state,
        "ships": [
            {
                "x": ship.x,
                "y": ship.y,
                "angle": ship_angles[id(ship)],
            }
            for ship in ships
        ],
    }

def publish_game_snapshot():
    if network_game_id and network_token:
        with network_state_lock:
            network_local_state.clear()
            network_local_state.update(current_game_snapshot())

def lock_ships():
    global ships_locked, dragging_ship, rotating_ship
    if ships_locked or not ship_geometry.all_ships_left_dock():
        return
    ships_locked = True
    dragging_ship = None
    rotating_ship = None
    if DEV_MODE:
        lock_button.config(text="Ships locked", state="disabled")
        game_status.set("Dev sandbox: ships locked. Test the laser.")
        return
    lock_button.config(text="Locking ships...", state="disabled")
    game_status.set("Locking ships on the Arcade server.")
    network_actions.put("lock")

def apply_network_state(response):
    global remote_player_state, multiplayer_ready, network_turn, ships_locked
    global dragging_ship, rotating_ship, fire_pending, fire_window_dismissed
    global server_ships_locked, network_state_initialized, a, b, lazer_state
    global own_hits, last_shot_event, last_shot_until, last_seen_shot_id
    global network_game_status
    own_state = response["own_state"]
    if not network_state_initialized:
        a = own_state["angle"]
        b = own_state["height"]
        lazer_state = own_state["laser_enabled"]
        angle_value.set(str(a))
        height_value.set(str(b))
        lazer_button.config(text=f"Lazer: {'On' if lazer_state else 'Off'}")
        for ship, ship_data in zip(ships, own_state["ships"]):
            ship.topleft = (round(ship_data["x"]), round(ship_data["y"]))
            ship_angles[id(ship)] = ship_data["angle"]
            ship_geometry.mark_ship_left_dock(ship, ship_data["angle"])
        network_state_initialized = True
        network_state_loaded.set()
    remote_player_state = response["opponent"]
    own_hits = own_state["hits"]
    game_status_messages = []
    for shot in response["shots"]:
        if shot["id"] <= last_seen_shot_id:
            continue
        last_seen_shot_id = shot["id"]
        last_shot_event = shot
        last_shot_until = time.monotonic() + SETTINGS.hit_marker_duration
        result = shot["result"].replace("_", " ").upper()
        if shot["sunk"]:
            result += " - SHIP SUNK"
        game_status_messages.append(
            f"{'You' if shot['shooter'] == 'you' else 'Opponent'}: {result}"
        )
    status = response["status"]
    network_game_status = status
    multiplayer_ready = status in ("active", "finished")
    previous_turn = network_turn
    network_turn = response["your_turn"]
    if network_turn != previous_turn:
        fire_pending = False
        fire_window_dismissed = False
    if own_state["ready"]:
        server_ships_locked = True
        ships_locked = True
        dragging_ship = None
        rotating_ship = None
        lock_button.config(text="Ships locked", state="disabled")
    else:
        if server_ships_locked:
            server_ships_locked = False
            ships_locked = False
        lock_button.config(
            text="Lock ships",
            state="normal" if ship_geometry.all_ships_left_dock() else "disabled",
        )

    if status == "waiting":
        fire_window.withdraw()
        base_message = "Waiting for an opponent. Share this room code."
    elif status == "placing":
        fire_window.withdraw()
        base_message = (
            "Ships locked. Waiting for the opponent to lock ships."
            if own_state["ready"]
            else "Move all ships out of the dock, then lock them."
        )
    elif status == "finished":
        fire_window.withdraw()
        base_message = (
            "You won!"
            if response["winner"] == "you"
            else "You lost. All your ships have been hit."
        )
    elif network_turn:
        if not fire_window_dismissed:
            fire_window.deiconify()
        fire_button.config(state="disabled" if fire_pending else "normal")
        base_message = "Your turn to fire."
    else:
        fire_window.withdraw()
        base_message = "Waiting for the opponent's shot."
    if game_status_messages:
        base_message += "\n" + " | ".join(game_status_messages)
    game_status.set(base_message)

def move_ship_smoothly(ship, target):
    start_x, start_y = ship.topleft
    delta_x = target.x - start_x
    delta_y = target.y - start_y
    steps = max(abs(delta_x), abs(delta_y))

    for step in range(1, steps + 1):
        next_x = round(start_x + delta_x * step / steps)
        next_y = round(start_y + delta_y * step / steps)
        candidate = ship.copy()
        candidate.topleft = (next_x, next_y)
        if ship_geometry.can_place_ship(ship, candidate):
            ship.update(candidate)
            ship_geometry.mark_ship_left_dock(ship)
            continue

        x_candidate = ship.copy()
        x_candidate.x = next_x
        y_candidate = ship.copy()
        y_candidate.y = next_y
        can_move_x = next_x != ship.x and ship_geometry.can_place_ship(
            ship, x_candidate
        )
        can_move_y = next_y != ship.y and ship_geometry.can_place_ship(
            ship, y_candidate
        )

        if can_move_x and can_move_y:
            if abs(delta_x) >= abs(delta_y):
                ship.x = next_x
            else:
                ship.y = next_y
        elif can_move_x:
            ship.x = next_x
        elif can_move_y:
            ship.y = next_y
        else:
            break
        ship_geometry.mark_ship_left_dock(ship)

def draw_ships():
    for ship_index, ship in enumerate(ships):
        angle = ship_angles[id(ship)]
        ship_surface = pg.Surface(ship.size, pg.SRCALPHA)
        pg.draw.ellipse(ship_surface, (0, 0, 0), ship_surface.get_rect())
        rotated_surface = pg.transform.rotate(
            ship_surface, -math.degrees(angle)
        )
        screen.blit(rotated_surface, rotated_surface.get_rect(center=ship.center))
        for segment in own_hits[ship_index]:
            local_y = -ship.height / 2 + (segment + 0.5) * ship_cell_size
            hit_center = (
                round(ship.centerx - local_y * math.sin(angle)),
                round(ship.centery + local_y * math.cos(angle)),
            )
            pg.draw.circle(screen, (255, 0, 0), hit_center, 8)
            pg.draw.circle(screen, (255, 255, 255), hit_center, 3)
        for point in ship_geometry.ship_movement_points(ship):
            pg.draw.circle(screen, (255, 255, 255), point, MOVE_POINT_RADIUS)
            pg.draw.circle(screen, (0, 100, 220), point, MOVE_POINT_RADIUS - 2)

        rotate_center = ship_geometry.ship_rotate_center(ship)
        pg.draw.circle(
            screen, (0, 100, 220), rotate_center, ROTATE_WIDGET_RADIUS
        )
        pg.draw.circle(
            screen, (255, 255, 255), rotate_center, ROTATE_WIDGET_RADIUS, 2
        )
        rotate_label = ship_control_font.render("R", True, (255, 255, 255))
        screen.blit(
            rotate_label,
            rotate_label.get_rect(center=rotate_center),
        )

def draw_ship_tray():
    pg.draw.rect(screen, (225, 225, 225), ship_tray_rect)
    pg.draw.rect(screen, (70, 70, 70), ship_tray_rect, 2)
    font = pg.font.Font(None, SETTINGS.ship_tray_font_size)
    label = font.render("Ships - drag to canvas", True, (0, 0, 0))
    screen.blit(label, (ship_tray_rect.left + 10, ship_tray_rect.top + 8))

def draw_canvas():
    pg.draw.rect(screen, (200, 200, 200), canvas_rect)

def draw_boundaries():
    pg.draw.rect(screen, (0, 0, 0), canvas_rect, 1)


controls = tk.Tk()
controls.title("Math Ships - Arcade")
controls.resizable(False, False)

username_value = tk.StringVar()
password_value = tk.StringVar()
room_code_value = tk.StringVar()
login_status = tk.StringVar(value="Searching for Arcade on your LAN...")
game_code_value = tk.StringVar()
game_status = tk.StringVar(
    value="Move all ships out of the dock, then lock them."
)
login_frame = tk.Frame(controls, padx=16, pady=16)
lobby_frame = tk.Frame(controls, padx=16, pady=16)
control_frame = tk.Frame(controls, padx=12, pady=12)
game_started = False
running = True


def show_lobby(username):
    login_frame.grid_remove()
    control_frame.grid_remove()
    lobby_frame.grid()
    lobby_username.config(text=f"Logged in as {username}")


def search_for_arcade_server():
    try:
        session = load_session()
    except SessionStoreError as error:
        server_discovery_events.put(("session_error", str(error)))
        session = None
    if session is not None:
        try:
            response = api_request(
                session["server_url"],
                "/api/auth/me",
                token=session["token"],
            )
        except ApiRequestError:
            pass
        else:
            server_discovery_events.put(
                (
                    "restored",
                    session["server_url"],
                    session["token"],
                    response["username"],
                )
            )
            return

    while not server_discovery_stop.is_set():
        try:
            server_url = discover_server()
        except OSError as error:
            server_discovery_events.put(("error", str(error)))
        else:
            if server_url:
                server_discovery_events.put(("found", server_url))
                return
        if server_discovery_stop.wait(SETTINGS.discovery_retry_seconds):
            return


def poll_server_discovery():
    global network_server_url, network_token, network_username
    try:
        discovery_event = server_discovery_events.get_nowait()
    except queue.Empty:
        discovery_event = None

    if discovery_event is not None and discovery_event[0] == "restored":
        _, network_server_url, network_token, network_username = discovery_event
        lobby_status.set("")
        show_lobby(network_username)
        return
    if discovery_event is not None and discovery_event[0] == "found":
        network_server_url = discovery_event[1]
        login_status.set("Arcade found on your LAN.")
        login_button.config(state="normal")
        register_button.config(state="normal")
        restore_saved_session()
        return
    if discovery_event is not None and discovery_event[0] == "error":
        login_status.set(f"LAN discovery error: {discovery_event[1]}. Retrying...")
    elif discovery_event is not None and discovery_event[0] == "session_error":
        login_status.set(str(discovery_event[1]))

    if running and not server_discovery_stop.is_set():
        controls.after(SETTINGS.discovery_poll_interval_ms, poll_server_discovery)


def start_server_discovery():
    login_status.set("Searching for Arcade on your LAN...")
    login_button.config(state="disabled")
    register_button.config(state="disabled")
    threading.Thread(
        target=search_for_arcade_server,
        daemon=True,
        name="mathships-lan-discovery",
    ).start()
    controls.after(SETTINGS.discovery_poll_interval_ms, poll_server_discovery)


def authenticate(path):
    global network_server_url, network_token, network_username
    server_url = network_server_url
    if not server_url:
        login_status.set("Searching for Arcade on your LAN...")
        return
    username = username_value.get().strip()
    password = password_value.get()
    if not username or not password:
        login_status.set("Enter your username and password.")
        return
    login_status.set("Connecting to Arcade...")
    controls.update_idletasks()
    try:
        response = api_request(
            server_url,
            path,
            method="POST",
            body={"username": username, "password": password},
        )
    except ApiRequestError as error:
        login_status.set(str(error))
        return

    network_server_url = server_url
    network_token = response["token"]
    network_username = response["username"]
    try:
        save_session(
            {
                "server_url": network_server_url,
                "token": network_token,
                "username": network_username,
            }
        )
    except SessionStoreError as error:
        lobby_status.set(f"Logged in, but could not remember this session: {error}")
    else:
        lobby_status.set("")
    show_lobby(network_username)


def restore_saved_session():
    global network_server_url, network_token, network_username
    try:
        session = load_session()
    except SessionStoreError as error:
        login_status.set(str(error))
        return
    if session is None:
        return
    try:
        response = api_request(
            network_server_url,
            "/api/auth/me",
            token=session["token"],
        )
    except ApiRequestError as error:
        if error.status_code == 401:
            try:
                clear_session()
            except SessionStoreError as clear_error:
                login_status.set(f"{error} {clear_error}")
                return
            login_status.set(
                "The saved login is not valid on this Arcade server. Please log in again."
            )
        else:
            login_status.set(str(error))
        return
    network_token = session["token"]
    network_username = response["username"]
    lobby_status.set("")
    show_lobby(network_username)


def create_game():
    try:
        response = api_request(
            network_server_url,
            "/api/multiplayer/games",
            method="POST",
            token=network_token,
        )
    except ApiRequestError as error:
        lobby_status.set(str(error))
        return
    start_game(response)


def join_game():
    code = room_code_value.get().strip().upper()
    if len(code) != 6 or any(
        character not in SETTINGS.game_code_characters for character in code
    ):
        lobby_status.set("Enter the six-character room code.")
        return
    try:
        response = api_request(
            network_server_url,
            f"/api/multiplayer/games/{code}/join",
            method="POST",
            token=network_token,
        )
    except ApiRequestError as error:
        lobby_status.set(str(error))
        return
    start_game(response)


def start_game(response):
    global network_game_id, network_state_initialized, game_started, screen
    global laser_overlay
    network_game_id = response["game_id"]
    network_stop.clear()
    network_state_loaded.clear()
    network_state_initialized = False
    game_started = True
    pg.display.set_caption("Math Ships - Battleship")
    screen = pg.display.set_mode((screen_width, screen_height))
    laser_overlay = pg.Surface(screen.get_size(), pg.SRCALPHA)
    laser_effects.set_overlay(laser_overlay)
    game_code_value.set(f"Room code: {network_game_id}")
    lobby_frame.grid_remove()
    login_frame.grid_remove()
    control_frame.grid()
    apply_network_state(response)
    publish_game_snapshot()
    worker = ArcadeWorker(
        network_server_url,
        network_token,
        network_game_id,
        network_actions,
        network_events,
        network_stop,
        network_state_loaded,
        network_state_lock,
        network_local_state,
    )
    threading.Thread(
        target=worker.run,
        daemon=True,
        name="mathships-network",
    ).start()


def start_dev_sandbox():
    global game_started, screen, laser_overlay
    global multiplayer_ready, network_turn, network_game_status
    global ships_locked, fire_pending, remote_player_state
    game_started = True
    multiplayer_ready = True
    network_turn = True
    network_game_status = "active"
    ships_locked = False
    fire_pending = False
    remote_player_state = None
    pg.display.set_caption("Math Ships - Dev Sandbox")
    screen = pg.display.set_mode((screen_width, screen_height))
    laser_overlay = pg.Surface(screen.get_size(), pg.SRCALPHA)
    laser_effects.set_overlay(laser_overlay)
    game_code_value.set("DEV SANDBOX - SOLO")
    game_status.set("Solo sandbox: place your ships and test the laser.")
    login_frame.grid_remove()
    lobby_frame.grid_remove()
    control_frame.grid()
    fire_button.config(state="normal")
    fire_window.deiconify()


def logout():
    global network_token, network_username
    try:
        api_request(
            network_server_url,
            "/api/auth/logout",
            method="POST",
            token=network_token,
        )
    except ApiRequestError as error:
        login_status.set(f"Logged out locally; Arcade reported: {error}")
    try:
        clear_session()
    except SessionStoreError as error:
        login_status.set(str(error))
    network_token = None
    network_username = None
    lobby_frame.grid_remove()
    login_frame.grid()


login_frame.grid(row=0, column=0, sticky="nsew")
tk.Label(login_frame, text="Math Ships", font=("TkDefaultFont", 18, "bold")).grid(
    row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
)
tk.Label(
    login_frame,
    text="Arcade server is detected automatically on your LAN.",
    wraplength=320,
    justify="left",
).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
tk.Label(login_frame, text="Username").grid(row=2, column=0, sticky="w")
username_entry = tk.Entry(login_frame, textvariable=username_value, width=34)
username_entry.grid(row=2, column=1, pady=3)
username_entry.bind(
    "<Return>", lambda _event: authenticate("/api/auth/login")
)
tk.Label(login_frame, text="Password").grid(row=3, column=0, sticky="w")
password_entry = tk.Entry(
    login_frame, textvariable=password_value, show="*", width=34
)
password_entry.grid(row=3, column=1, pady=3)
password_entry.bind(
    "<Return>", lambda _event: authenticate("/api/auth/login")
)
login_button = tk.Button(
    login_frame,
    text="Log in",
    command=lambda: authenticate("/api/auth/login"),
    state="disabled",
)
login_button.grid(row=4, column=0, sticky="ew", pady=(10, 0))
register_button = tk.Button(
    login_frame,
    text="Create account",
    command=lambda: authenticate("/api/auth/register"),
    state="disabled",
)
register_button.grid(row=4, column=1, sticky="ew", pady=(10, 0))
tk.Label(
    login_frame, textvariable=login_status, wraplength=320, justify="left"
).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

lobby_status = tk.StringVar()
lobby_frame.grid_remove()
lobby_username = tk.Label(lobby_frame)
lobby_username.grid(row=0, column=0, columnspan=2, sticky="w")
tk.Button(lobby_frame, text="Log out", command=logout).grid(
    row=0, column=2, sticky="e"
)
tk.Button(lobby_frame, text="Create game", command=create_game).grid(
    row=1, column=0, columnspan=3, sticky="ew", pady=(12, 8)
)
tk.Label(lobby_frame, text="Join with room code").grid(
    row=2, column=0, sticky="w"
)
tk.Entry(lobby_frame, textvariable=room_code_value, width=16).grid(
    row=2, column=1, padx=6
)
tk.Button(lobby_frame, text="Join", command=join_game).grid(
    row=2, column=2, sticky="ew"
)
tk.Label(
    lobby_frame, textvariable=lobby_status, wraplength=320, justify="left"
).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

angle_value = tk.StringVar(value=str(a))
height_value = tk.StringVar(value=str(b))
angle_value.trace_add("write", update_angle)
height_value.trace_add("write", update_height)
validate_number = (controls.register(valid_number), "%P")
tk.Label(control_frame, textvariable=game_code_value).grid(
    row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
)
tk.Label(control_frame, text="Angle (radians)").grid(row=1, column=0, sticky="w")
angle_left_button = tk.Button(control_frame, text="←")
angle_left_button.grid(row=1, column=1, padx=(8, 0))
angle_left_button.bind(
    "<ButtonPress-1>",
    lambda event: start_adjustment(
        event, lambda: adjust_angle(SETTINGS.angle_adjust_step)
    ),
)
angle_entry = tk.Entry(
    control_frame,
    textvariable=angle_value,
    width=10,
    validate="key",
    validatecommand=validate_number,
)
angle_entry.grid(row=1, column=2)
angle_entry.bind("<FocusOut>", normalize_angle)
angle_right_button = tk.Button(control_frame, text="→")
angle_right_button.grid(row=1, column=3, padx=(0, 8))
angle_right_button.bind(
    "<ButtonPress-1>",
    lambda event: start_adjustment(
        event, lambda: adjust_angle(-SETTINGS.angle_adjust_step)
    ),
)
tk.Label(control_frame, text="Laser height").grid(
    row=2, column=0, sticky="w", pady=(8, 0)
)
height_left_button = tk.Button(control_frame, text="←")
height_left_button.grid(row=2, column=1, padx=(8, 0), pady=(8, 0))
height_left_button.bind(
    "<ButtonPress-1>",
    lambda event: start_adjustment(
        event, lambda: adjust_height(SETTINGS.height_adjust_step)
    ),
)
height_entry = tk.Entry(
    control_frame,
    textvariable=height_value,
    width=10,
    validate="key",
    validatecommand=validate_number,
)
height_entry.grid(row=2, column=2, pady=(8, 0))
height_entry.bind("<FocusOut>", normalize_height)
height_right_button = tk.Button(control_frame, text="→")
height_right_button.grid(row=2, column=3, padx=(0, 8), pady=(8, 0))
height_right_button.bind(
    "<ButtonPress-1>",
    lambda event: start_adjustment(
        event, lambda: adjust_height(-SETTINGS.height_adjust_step)
    ),
)
controls.bind_all("<ButtonRelease-1>", stop_adjustment)
lazer_button = tk.Button(
    control_frame,
    text=f"Lazer: {'On' if lazer_state else 'Off'}",
    command=toggle_lazer,
)
if SETTINGS.show_laser_toggle:
    lazer_button.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
lock_button = tk.Button(
    control_frame,
    text="Lock ships",
    command=lock_ships,
    state="disabled",
)
lock_button.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))
tk.Label(
    control_frame,
    textvariable=game_status,
    wraplength=SETTINGS.control_wrap_length,
).grid(
    row=5, column=0, columnspan=4, sticky="w", pady=(8, 0)
)
fire_window = tk.Toplevel(controls)
fire_window.title("Math Ships - Fire")
fire_window.resizable(False, False)
fire_window.withdraw()
fire_button = tk.Button(
    fire_window,
    text="FIRE",
    command=fire_lazer,
    bg="#087f9c",
    activebackground="#00bcd4",
)
fire_button.pack(padx=16, pady=16, ipadx=24, ipady=12)


def close_fire_window():
    global fire_window_dismissed
    fire_window_dismissed = True
    fire_window.withdraw()


fire_window.protocol("WM_DELETE_WINDOW", close_fire_window)


def close_controls():
    global running
    running = False
    network_stop.set()
    server_discovery_stop.set()


controls.protocol("WM_DELETE_WINDOW", close_controls)
if DEV_MODE:
    controls.after(SETTINGS.startup_delay_ms, start_dev_sandbox)
else:
    controls.after(SETTINGS.startup_delay_ms, start_server_discovery)

while running:
    controls.update()
    if not game_started:
        time.sleep(SETTINGS.idle_sleep_seconds)
        continue

    if not ships_locked:
        lock_button.config(
            state="normal" if ship_geometry.all_ships_left_dock() else "disabled"
        )
    while True:
        try:
            network_event = network_events.get_nowait()
        except queue.Empty:
            break
        if network_event[0] == "state":
            apply_network_state(network_event[1])
        elif network_event[0] == "error":
            fire_pending = False
            game_status.set(f"Arcade connection error: {network_event[1]}")
            if len(network_event) > 2 and network_event[2] == "lock":
                ships_locked = False
                lock_button.config(
                    text="Lock ships",
                    state="normal"
                    if ship_geometry.all_ships_left_dock()
                    else "disabled",
                )
            if network_turn and multiplayer_ready:
                fire_button.config(state="normal")
    for event in pg.event.get():
        if event.type == pg.QUIT:
            running = False
        elif event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
            toggle_lazer()
        elif (
            event.type == pg.KEYDOWN
            and event.key == pg.K_r
            and dragging_ship is not None
            and not ships_locked
        ):
            ship_geometry.rotate_ship(dragging_ship, 1)
        elif (
            event.type == pg.MOUSEBUTTONDOWN
            and event.button == 1
            and not ships_locked
        ):
            for ship in reversed(ships):
                if ship_geometry.point_in_circle(
                    event.pos,
                    ship_geometry.ship_rotate_center(ship),
                    ROTATE_WIDGET_RADIUS,
                ):
                    rotating_ship = ship
                    last_rotate_pointer_angle = math.atan2(
                        event.pos[1] - ship.centery,
                        event.pos[0] - ship.centerx,
                    )
                    rotate_degrees_remainder = 0.0
                    break
                if (
                    any(
                        ship_geometry.point_in_circle(
                            event.pos, point, MOVE_POINT_RADIUS + 2
                        )
                        for point in ship_geometry.ship_movement_points(ship)
                    )
                    or ship_geometry.point_inside_ship(ship, event.pos)
                ):
                    dragging_ship = ship
                    drag_offset = (event.pos[0] - ship.x, event.pos[1] - ship.y)
                    break
        elif event.type == pg.MOUSEBUTTONUP and event.button == 1:
            dragging_ship = None
            rotating_ship = None
            rotate_degrees_remainder = 0.0
        elif event.type == pg.MOUSEMOTION and rotating_ship is not None:
            pointer_angle = math.atan2(
                event.pos[1] - rotating_ship.centery,
                event.pos[0] - rotating_ship.centerx,
            )
            angle_delta = math.atan2(
                math.sin(pointer_angle - last_rotate_pointer_angle),
                math.cos(pointer_angle - last_rotate_pointer_angle),
            )
            last_rotate_pointer_angle = pointer_angle
            rotate_degrees_remainder += math.degrees(angle_delta)
            whole_degrees = math.trunc(rotate_degrees_remainder)
            if whole_degrees:
                ship_geometry.rotate_ship(rotating_ship, whole_degrees)
                rotate_degrees_remainder -= whole_degrees
        elif event.type == pg.MOUSEMOTION and dragging_ship is not None:
            target = dragging_ship.copy()
            target.topleft = (
                event.pos[0] - drag_offset[0],
                event.pos[1] - drag_offset[1],
            )
            target.clamp_ip(screen_rect)
            move_ship_smoothly(dragging_ship, target)

    screen.fill((255, 255, 255))
    draw_canvas()
    draw_ship_tray()
    draw_ships()
    draw_boundaries()
    laser_overlay.fill((0, 0, 0, 0))
    effect_time = time.monotonic()
    lazer_x = side_margin
    lazer_y = canvas_rect.bottom - b
    lazer_angle = -a
    if lazer_state:
        laser_effects.draw_burns(effect_time)
    draw_lazer(
        lazer_x,
        lazer_y,
        lazer_angle,
        lazer_state,
        (0, 145, 210, 105),
    )
    if (
        remote_player_state
        and network_game_status == "active"
        and not network_turn
    ):
        draw_lazer(
            lazer_x,
            canvas_rect.bottom - remote_player_state["height"],
            -remote_player_state["angle"],
            remote_player_state["laser_enabled"],
            (155, 40, 220, 110),
        )
    if lazer_state:
        laser_effects.draw_pulse(effect_time)
    if (
        last_shot_event
        and last_shot_event["shooter"] == "you"
        and last_shot_event["impact"]
        and effect_time < last_shot_until
    ):
        impact = last_shot_event["impact"]
        color = (0, 180, 0) if last_shot_event["result"] == "hit" else (255, 140, 0)
        pg.draw.circle(
            laser_overlay,
            color,
            (round(impact["x"]), round(impact["y"])),
            12,
            3,
        )
    screen.blit(laser_overlay, (0, 0))
    draw_lazerCannon(lazer_x, lazer_y, lazer_angle)
    pg.display.flip()
    publish_game_snapshot()

network_stop.set()
controls.destroy()
pg.quit()
