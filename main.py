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


DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
ARCADE_GAME_CODE_PATTERN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
network_server_url = None
network_token = None
network_username = None
network_game_id = None

screen_width = 1600
screen_height = 1200
side_margin = 150
canvas_top = 250
ship_cell_size = 40
canvas_rect = pg.Rect(
    side_margin,
    canvas_top,
    screen_width - 2 * side_margin,
    screen_height - canvas_top - side_margin,
)
screen_rect = pg.Rect(0, 0, screen_width, screen_height)
ship_tray_rect = pg.Rect(
    canvas_rect.left,
    10,
    canvas_rect.width,
    canvas_top - 10,
)
ship_lengths = (2, 2, 3, 4)
ship_gap = 20
MOVE_POINT_RADIUS = 7
ROTATE_WIDGET_RADIUS = 11
ship_total_width = len(ship_lengths) * ship_cell_size + ship_gap * (
    len(ship_lengths) - 1
)
tray_board_left = max(canvas_rect.left, ship_tray_rect.left)
tray_board_right = min(canvas_rect.right, ship_tray_rect.right)
ship_x = tray_board_left + (tray_board_right - tray_board_left - ship_total_width) // 2
ship_y = ship_tray_rect.top + 50
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

a = 0 #rotate 
a_max = 1.57
b = 0 #up down
b_max = canvas_rect.height

b = b *100
a = a * math.pi / 180
lazer_state = True
lazer_length = 3000
fire_button_fired = False
laser_shot_until = 0.0
remote_player_state = None
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
network_stop = threading.Event()
network_state_loaded = threading.Event()
network_state_lock = threading.Lock()
network_local_state = {}
network_state_initialized = False


pg.init()
screen = None
laser_overlay = None
ship_control_font = pg.font.Font(None, 18)

def draw_lazerCannon(x, y, angle):
    # Draw a simple ship
    points = [
        (x + 20 * math.cos(angle + math.pi/4), y + 20 * math.sin(angle + math.pi/4)),
        (x + 20 * math.cos(angle + 3*math.pi/4), y + 20 * math.sin(angle + 3*math.pi/4)),
        (x + 20 * math.cos(angle - 3*math.pi/4), y + 20 * math.sin(angle - 3*math.pi/4)),
        (x + 20 * math.cos(angle - math.pi/4), y + 20 * math.sin(angle - math.pi/4))
    ]
    pg.draw.polygon(screen, (0, 0, 0), points)

def draw_lazer(x, y, angle, enabled, color):
    if enabled:
        end_x = x + lazer_length * math.cos(angle)
        end_y = y + lazer_length * math.sin(angle)
        pg.draw.line(
            laser_overlay, color, (x, y), (end_x, end_y), 3
        )

def fire_lazer():
    global fire_button_fired, fire_pending, laser_shot_until
    if not all_ships_left_dock():
        return
    if not multiplayer_ready or not network_turn or fire_pending:
        return
    fire_button_fired = True
    laser_shot_until = time.monotonic() + 0.15
    fire_button.config(bg="red", activebackground="red")
    fire_pending = True
    fire_button.config(state="disabled")
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
        50, lambda: repeat_adjustment(action)
    )

def start_adjustment(_event, action):
    global repeat_after_id
    stop_adjustment()
    action()
    repeat_after_id = controls.after(
        300, lambda: repeat_adjustment(action)
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

def can_place_ship(ship, candidate, candidate_angle=None):
    if candidate_angle is None:
        candidate_angle = ship_angles[id(ship)]
    if id(ship) in ships_left_dock and overlaps_ship_dock(
        candidate, candidate_angle
    ):
        return False
    return is_in_ship_area(candidate, candidate_angle) and all(
        other is ship
        or not ships_overlap(
            candidate,
            other,
            candidate_angle,
            ship_angles[id(other)],
        )
        for other in ships
    )

def rotate_ship(ship, delta_degrees):
    current_angle = ship_angles[id(ship)]
    direction = 1 if delta_degrees > 0 else -1
    changed = False
    for _ in range(abs(int(delta_degrees))):
        candidate_angle = current_angle + math.radians(direction)
        candidate_angle = (candidate_angle + math.pi) % (2 * math.pi) - math.pi
        if not can_place_ship(ship, ship, candidate_angle):
            break
        current_angle = candidate_angle
        ship_angles[id(ship)] = current_angle
        mark_ship_left_dock(ship, current_angle)
        changed = True
    return changed

def ship_bounds(ship, angle=None):
    if angle is None:
        angle = ship_angles[id(ship)]
    cosine = abs(math.cos(angle))
    sine = abs(math.sin(angle))
    half_width = (ship.width * cosine + ship.height * sine) / 2
    half_height = (ship.width * sine + ship.height * cosine) / 2
    return (
        ship.centerx - half_width,
        ship.centery - half_height,
        ship.centerx + half_width,
        ship.centery + half_height,
    )

def overlaps_ship_dock(ship, angle=None):
    left, top, right, bottom = ship_bounds(ship, angle)
    return (
        left < ship_tray_rect.right
        and right > ship_tray_rect.left
        and top < ship_tray_rect.bottom
        and bottom > ship_tray_rect.top
    )

def mark_ship_left_dock(ship, angle=None):
    if not overlaps_ship_dock(ship, angle):
        ships_left_dock.add(id(ship))

def all_ships_left_dock():
    return all(
        not overlaps_ship_dock(ship, ship_angles[id(ship)])
        for ship in ships
    )

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

def arcade_game_request(path, method="GET", body=None):
    if not network_server_url or not network_token:
        raise RuntimeError("You are not connected to the Arcade server.")
    return api_request(
        network_server_url,
        path,
        method=method,
        token=network_token,
        body=body,
    )

def network_worker():
    game_path = f"/api/multiplayer/games/{network_game_id}"
    game_finished = False
    while not network_stop.is_set():
        try:
            response = arcade_game_request(game_path)
        except ApiRequestError as error:
            network_events.put(("error", str(error)))
            if network_stop.wait(1):
                return
            continue
        game_finished = response["status"] == "finished"
        network_events.put(("state", response))
        if network_state_loaded.wait(5):
            break
        if network_stop.is_set():
            return

    while not network_stop.is_set():
        try:
            action = network_actions.get_nowait()
        except queue.Empty:
            action = None

        if action:
            try:
                if action == "lock":
                    response = arcade_game_request(
                        f"{game_path}/lock", method="POST"
                    )
                else:
                    response = arcade_game_request(
                        f"{game_path}/fire", method="POST"
                    )
            except ApiRequestError as error:
                network_events.put(("error", str(error), action))
                if network_stop.wait(1):
                    return
                continue
            game_finished = response["status"] == "finished"
            network_events.put(("state", response))

        try:
            if game_finished:
                response = arcade_game_request(game_path)
            else:
                with network_state_lock:
                    snapshot = dict(network_local_state)
                response = arcade_game_request(
                    f"{game_path}/state",
                    method="PUT",
                    body=snapshot,
                )
        except ApiRequestError as error:
            if error.status_code == 409:
                game_finished = True
                continue
            network_events.put(("error", str(error)))
            if network_stop.wait(1):
                return
            continue
        game_finished = response["status"] == "finished"
        network_events.put(("state", response))
        if network_stop.wait(0.1):
            return

def lock_ships():
    global ships_locked, dragging_ship, rotating_ship
    if ships_locked or not all_ships_left_dock():
        return
    ships_locked = True
    dragging_ship = None
    rotating_ship = None
    lock_button.config(text="Locking ships...", state="disabled")
    game_status.set("Locking ships on the Arcade server.")
    network_actions.put("lock")

def apply_network_state(response):
    global remote_player_state, multiplayer_ready, network_turn, ships_locked
    global dragging_ship, rotating_ship, fire_pending, fire_window_dismissed
    global server_ships_locked, network_state_initialized, a, b, lazer_state
    global own_hits, last_shot_event, last_shot_until, last_seen_shot_id
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
            mark_ship_left_dock(ship, ship_data["angle"])
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
        last_shot_until = time.monotonic() + 1.0
        result = shot["result"].replace("_", " ").upper()
        if shot["sunk"]:
            result += " - SHIP SUNK"
        game_status_messages.append(
            f"{'You' if shot['shooter'] == 'you' else 'Opponent'}: {result}"
        )
    status = response["status"]
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
            state="normal" if all_ships_left_dock() else "disabled",
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

def is_in_ship_area(ship, angle=None):
    left, top, right, bottom = ship_bounds(ship, angle)

    def inside(area):
        return (
            left >= area.left
            and top >= area.top
            and right <= area.right
            and bottom <= area.bottom
        )

    if inside(canvas_rect) or inside(ship_tray_rect):
        return True

    crosses_canvas_top = top < canvas_rect.top < bottom
    tray_board_left = max(canvas_rect.left, ship_tray_rect.left)
    tray_board_right = min(canvas_rect.right, ship_tray_rect.right)
    return (
        crosses_canvas_top
        and top >= ship_tray_rect.top
        and bottom <= canvas_rect.bottom
        and left >= tray_board_left
        and right <= tray_board_right
    )

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
        if can_place_ship(ship, candidate):
            ship.update(candidate)
            mark_ship_left_dock(ship)
            continue

        x_candidate = ship.copy()
        x_candidate.x = next_x
        y_candidate = ship.copy()
        y_candidate.y = next_y
        can_move_x = next_x != ship.x and can_place_ship(ship, x_candidate)
        can_move_y = next_y != ship.y and can_place_ship(ship, y_candidate)

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
        mark_ship_left_dock(ship)

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
        for point in ship_movement_points(ship):
            pg.draw.circle(screen, (255, 255, 255), point, MOVE_POINT_RADIUS)
            pg.draw.circle(screen, (0, 100, 220), point, MOVE_POINT_RADIUS - 2)

        rotate_center = ship_rotate_center(ship)
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

def ship_movement_points(ship):
    angle = ship_angles[id(ship)]
    cosine = math.cos(angle)
    sine = math.sin(angle)
    corners = (
        (-ship.width / 2, -ship.height / 2),
        (ship.width / 2, -ship.height / 2),
        (ship.width / 2, ship.height / 2),
        (-ship.width / 2, ship.height / 2),
    )
    return tuple(
        (
            round(ship.centerx + x * cosine - y * sine),
            round(ship.centery + x * sine + y * cosine),
        )
        for x, y in corners
    )

def ship_rotate_center(ship):
    angle = ship_angles[id(ship)]
    local_y = ship.height / 2 + ROTATE_WIDGET_RADIUS + 2
    return (
        round(ship.centerx - local_y * math.sin(angle)),
        round(ship.centery + local_y * math.cos(angle)),
    )

def point_in_circle(point, center, radius):
    return (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2 <= radius**2

def draw_ship_tray():
    pg.draw.rect(screen, (225, 225, 225), ship_tray_rect)
    pg.draw.rect(screen, (70, 70, 70), ship_tray_rect, 2)
    font = pg.font.Font(None, 28)
    label = font.render("Ships - drag to canvas", True, (0, 0, 0))
    screen.blit(label, (ship_tray_rect.left + 10, ship_tray_rect.top + 8))

def ellipse_support(ellipse, direction, angle=0.0):
    radius_x = ellipse.width / 2
    radius_y = ellipse.height / 2
    cosine = math.cos(angle)
    sine = math.sin(angle)
    local_direction = (
        cosine * direction[0] + sine * direction[1],
        -sine * direction[0] + cosine * direction[1],
    )
    denominator = math.hypot(
        radius_x * local_direction[0], radius_y * local_direction[1]
    )
    if denominator == 0:
        return ellipse.centerx, ellipse.centery
    local_x = radius_x**2 * local_direction[0] / denominator
    local_y = radius_y**2 * local_direction[1] / denominator
    return (
        ellipse.centerx + local_x * cosine - local_y * sine,
        ellipse.centery + local_x * sine + local_y * cosine,
    )

def minkowski_support(first, second, direction, first_angle, second_angle):
    first_point = ellipse_support(first, direction, first_angle)
    second_point = ellipse_support(
        second, (-direction[0], -direction[1]), second_angle
    )
    return first_point[0] - second_point[0], first_point[1] - second_point[1]

def dot(first, second):
    return first[0] * second[0] + first[1] * second[1]

def triple_product(first, second, third):
    return (
        second[0] * dot(first, third) - first[0] * dot(second, third),
        second[1] * dot(first, third) - first[1] * dot(second, third),
    )

def update_simplex(simplex):
    point_a = simplex[-1]
    to_origin = (-point_a[0], -point_a[1])

    if len(simplex) == 2:
        point_b = simplex[-2]
        ab = (point_b[0] - point_a[0], point_b[1] - point_a[1])
        if dot(ab, to_origin) > 0:
            direction = triple_product(ab, to_origin, ab)
            if dot(direction, direction) < 1e-12:
                return True, (0, 0)
            return False, direction
        simplex[:] = [point_a]
        return False, to_origin

    point_b, point_c = simplex[-2], simplex[-3]
    ab = (point_b[0] - point_a[0], point_b[1] - point_a[1])
    ac = (point_c[0] - point_a[0], point_c[1] - point_a[1])
    if abs(ab[0] * ac[1] - ab[1] * ac[0]) < 1e-12:
        if dot(ab, ab) >= dot(ac, ac):
            simplex[:] = [point_b, point_a]
        else:
            simplex[:] = [point_c, point_a]
        return update_simplex(simplex)

    ab_perpendicular = triple_product(ac, ab, ab)
    if dot(ab_perpendicular, to_origin) > 0:
        simplex[:] = [point_b, point_a]
        return False, ab_perpendicular

    ac_perpendicular = triple_product(ab, ac, ac)
    if dot(ac_perpendicular, to_origin) > 0:
        simplex[:] = [point_c, point_a]
        return False, ac_perpendicular

    return True, (0, 0)

def ships_overlap(first, second, first_angle=0.0, second_angle=0.0):
    first_left, first_top, first_right, first_bottom = ship_bounds(
        first, first_angle
    )
    second_left, second_top, second_right, second_bottom = ship_bounds(
        second, second_angle
    )
    if (
        first_right <= second_left
        or second_right <= first_left
        or first_bottom <= second_top
        or second_bottom <= first_top
    ):
        return False
    direction = (second.centerx - first.centerx, second.centery - first.centery)
    if direction == (0, 0):
        return True

    simplex = [
        minkowski_support(first, second, direction, first_angle, second_angle)
    ]
    direction = (-simplex[0][0], -simplex[0][1])
    for _ in range(64):
        if dot(direction, direction) < 1e-12:
            return True
        point = minkowski_support(
            first, second, direction, first_angle, second_angle
        )
        if dot(point, direction) <= 1e-10:
            return False
        if any(
            math.hypot(point[0] - previous[0], point[1] - previous[1]) < 1e-10
            for previous in simplex
        ):
            return False
        simplex.append(point)
        overlaps, direction = update_simplex(simplex)
        if overlaps:
            return True
    return True

def point_inside_ship(ship, point):
    angle = ship_angles[id(ship)]
    delta_x = point[0] - ship.centerx
    delta_y = point[1] - ship.centery
    horizontal = (
        delta_x * math.cos(angle) + delta_y * math.sin(angle)
    ) / (ship.width / 2)
    vertical = (
        -delta_x * math.sin(angle) + delta_y * math.cos(angle)
    ) / (ship.height / 2)
    return horizontal**2 + vertical**2 <= 1

def draw_canvas():
    pg.draw.rect(screen, (200, 200, 200), canvas_rect)

def draw_boundaries():
    pg.draw.rect(screen, (0, 0, 0), canvas_rect, 1)


controls = tk.Tk()
controls.title("Math Ships - Arcade")
controls.resizable(False, False)

server_url_value = tk.StringVar(value=DEFAULT_SERVER_URL)
username_value = tk.StringVar()
password_value = tk.StringVar()
room_code_value = tk.StringVar()
login_status = tk.StringVar()
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


def authenticate(path):
    global network_server_url, network_token, network_username
    server_url = server_url_value.get().strip().rstrip("/")
    if not server_url.startswith(("http://", "https://")):
        login_status.set("Enter a server URL beginning with http:// or https://.")
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
    server_url_value.set(session["server_url"])
    try:
        response = api_request(
            session["server_url"],
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
            login_status.set("Your saved login expired. Please log in again.")
        else:
            login_status.set(str(error))
        return
    network_server_url = session["server_url"]
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
    if len(code) != 6 or any(character not in ARCADE_GAME_CODE_PATTERN for character in code):
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
    game_code_value.set(f"Room code: {network_game_id}")
    lobby_frame.grid_remove()
    login_frame.grid_remove()
    control_frame.grid()
    apply_network_state(response)
    publish_game_snapshot()
    threading.Thread(target=network_worker, daemon=True).start()


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
tk.Label(login_frame, text="Arcade server").grid(row=1, column=0, sticky="w")
tk.Entry(login_frame, textvariable=server_url_value, width=34).grid(
    row=1, column=1, pady=3
)
tk.Label(login_frame, text="Username").grid(row=2, column=0, sticky="w")
tk.Entry(login_frame, textvariable=username_value, width=34).grid(
    row=2, column=1, pady=3
)
tk.Label(login_frame, text="Password").grid(row=3, column=0, sticky="w")
tk.Entry(login_frame, textvariable=password_value, show="*", width=34).grid(
    row=3, column=1, pady=3
)
tk.Button(
    login_frame,
    text="Log in",
    command=lambda: authenticate("/api/auth/login"),
).grid(row=4, column=0, sticky="ew", pady=(10, 0))
tk.Button(
    login_frame,
    text="Create account",
    command=lambda: authenticate("/api/auth/register"),
).grid(row=4, column=1, sticky="ew", pady=(10, 0))
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
    lambda event: start_adjustment(event, lambda: adjust_angle(0.01)),
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
    lambda event: start_adjustment(event, lambda: adjust_angle(-0.01)),
)
tk.Label(control_frame, text="Laser height").grid(
    row=2, column=0, sticky="w", pady=(8, 0)
)
height_left_button = tk.Button(control_frame, text="←")
height_left_button.grid(row=2, column=1, padx=(8, 0), pady=(8, 0))
height_left_button.bind(
    "<ButtonPress-1>",
    lambda event: start_adjustment(event, lambda: adjust_height(10)),
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
    lambda event: start_adjustment(event, lambda: adjust_height(-10)),
)
controls.bind_all("<ButtonRelease-1>", stop_adjustment)
lazer_button = tk.Button(
    control_frame,
    text=f"Lazer: {'On' if lazer_state else 'Off'}",
    command=toggle_lazer,
)
lazer_button.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
lock_button = tk.Button(
    control_frame,
    text="Lock ships",
    command=lock_ships,
    state="disabled",
)
lock_button.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))
tk.Label(control_frame, textvariable=game_status, wraplength=250).grid(
    row=5, column=0, columnspan=4, sticky="w", pady=(8, 0)
)
fire_window = tk.Toplevel(controls)
fire_window.title("Math Ships - Fire")
fire_window.resizable(False, False)
fire_window.withdraw()
fire_button = tk.Button(fire_window, text="FIRE", command=fire_lazer)
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


controls.protocol("WM_DELETE_WINDOW", close_controls)
controls.after(100, restore_saved_session)

while running:
    controls.update()
    if not game_started:
        time.sleep(0.01)
        continue

    if not ships_locked:
        lock_button.config(
            state="normal" if all_ships_left_dock() else "disabled"
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
                    state="normal" if all_ships_left_dock() else "disabled",
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
            rotate_ship(dragging_ship, 1)
        elif (
            event.type == pg.MOUSEBUTTONDOWN
            and event.button == 1
            and not ships_locked
        ):
            for ship in reversed(ships):
                if point_in_circle(
                    event.pos,
                    ship_rotate_center(ship),
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
                        point_in_circle(
                            event.pos, point, MOVE_POINT_RADIUS + 2
                        )
                        for point in ship_movement_points(ship)
                    )
                    or point_inside_ship(ship, event.pos)
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
                rotate_ship(rotating_ship, whole_degrees)
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
    lazer_x = side_margin
    lazer_y = canvas_rect.bottom - b
    lazer_angle = -a
    draw_lazer(
        lazer_x,
        lazer_y,
        lazer_angle,
        lazer_state or time.monotonic() < laser_shot_until,
        (255, 0, 0, 80),
    )
    if remote_player_state:
        draw_lazer(
            lazer_x,
            canvas_rect.bottom - remote_player_state["height"],
            -remote_player_state["angle"],
            remote_player_state["laser_enabled"],
            (0, 80, 255, 100),
        )
    if (
        last_shot_event
        and last_shot_event["impact"]
        and time.monotonic() < last_shot_until
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
