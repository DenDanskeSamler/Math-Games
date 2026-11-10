"""
& d:\Fbamse\Project\VCTGames\.venv\Scripts\python.exe d:/Fbamse/Project/VCTGames/sample_apps/MathShips/main.py
"""
import pygame as pg
import math
import time

screen_width = 1600
screen_height = 1200
side_margin = 150
ship_cell_size = 40
canvas_rect = pg.Rect(side_margin, side_margin, screen_width - 2*side_margin, screen_height - 2*side_margin)
ships = [
    pg.Rect(side_margin + 70, side_margin + 80, ship_cell_size, 2 * ship_cell_size),
    pg.Rect(side_margin + 130, side_margin + 80, ship_cell_size, 2 * ship_cell_size),
    pg.Rect(side_margin + 200, side_margin + 80, ship_cell_size, 3 * ship_cell_size),
    pg.Rect(side_margin + 280, side_margin + 80, ship_cell_size, 4 * ship_cell_size),
]
dragging_ship = None
drag_offset = (0, 0)

a = 0 #rotate 
a_max = 1.57
b = 0 #up down
b_max = 900

b = b *100
a = a * math.pi / 180
input_a_box = pg.Rect(10, 10, side_margin - 20, 50)
input_a_selected = False
input_b_box = pg.Rect(10, 70, side_margin - 20, 50)
input_b_selected = False
lazer_button = pg.Rect(10, 125, side_margin - 20, 50)

lazer_state = True
lazer_length = 3000


pg.display.set_caption("Math Ships")
screen = pg.display.set_mode((screen_width, screen_height))
pg.init()

def sidebar():
    pg.draw.rect(screen, (150, 150, 150), (0, 0, side_margin, screen_height))
    #input a
    #add a click event to select it
    pg.draw.rect(screen, (200, 200, 200), input_a_box)  # input a box
    if input_a_selected:
        pg.draw.rect(screen, (0, 100, 220), input_a_box, 3)

    input_a_text = f"a: {a}"  # display the current value of a
    font = pg.font.Font(None, 36)
    text_surface = font.render(input_a_text, True, (0, 0, 0))
    screen.blit(text_surface, (15, 15))

    #input b
    pg.draw.rect(screen, (200, 200, 200), input_b_box)  # input b box
    if input_b_selected:
        pg.draw.rect(screen, (0, 100, 220), input_b_box, 3)

    input_b_text = f"b: {b}"  # display the current value of b
    text_surface = font.render(input_b_text, True, (0, 0, 0))
    screen.blit(text_surface, (15, 75))

    pg.draw.rect(screen, (200, 200, 200), lazer_button)
    pg.draw.rect(screen, (0, 100, 220) if lazer_state else (0, 0, 0), lazer_button, 3)
    lazer_text = f"Lazer: {'On' if lazer_state else 'Off'}"
    text_surface = font.render(lazer_text, True, (0, 0, 0))
    screen.blit(text_surface, (15, 132))


def handle_input():
    global a
    keys = pg.key.get_pressed()
    if input_a_selected:
        if keys[pg.K_LEFT]:
            a += 0.01
            if a > a_max:
                a = a_max
            a = round(a, 2)
            time.sleep(0.1)
        if keys[pg.K_RIGHT]:
            a -= 0.01
            if a < -a_max:
                a = -a_max
            a = round(a, 2)
            time.sleep(0.1)
            
    global b
    if input_b_selected:
        keys = pg.key.get_pressed()
        if keys[pg.K_DOWN]:
            b -= 10
            if b < 0:
                b = 0
            b = round(b, 1)
            time.sleep(0.1)
        if keys[pg.K_UP]:
            b += 10
            if b > b_max:
                b = b_max
            b = round(b, 1)
            time.sleep(0.1)


def draw_lazerCannon(x, y, angle):
    # Draw a simple ship
    points = [
        (x + 20 * math.cos(angle + math.pi/4), y + 20 * math.sin(angle + math.pi/4)),
        (x + 20 * math.cos(angle + 3*math.pi/4), y + 20 * math.sin(angle + 3*math.pi/4)),
        (x + 20 * math.cos(angle - 3*math.pi/4), y + 20 * math.sin(angle - 3*math.pi/4)),
        (x + 20 * math.cos(angle - math.pi/4), y + 20 * math.sin(angle - math.pi/4))
    ]
    pg.draw.polygon(screen, (0, 0, 0), points)

def draw_lazer(x, y, angle):
    # Draw a simple laser coming out of the ship
    if lazer_state:
        end_x = x + lazer_length * math.cos(angle)
        end_y = y + lazer_length * math.sin(angle)
        pg.draw.line(screen, (255, 0, 0), (x, y), (end_x, end_y), 3)

def can_place_ship(ship, candidate):
    return canvas_rect.contains(candidate) and all(
        other is ship or not candidate.colliderect(other)
        for other in ships
    )

def draw_ships():
    for ship in ships:
        pg.draw.rect(screen, (0, 0, 0), ship)
        for x in range(ship.left + ship_cell_size, ship.right, ship_cell_size):
            pg.draw.line(screen, (200, 200, 200), (x, ship.top), (x, ship.bottom), 2)
        for y in range(ship.top + ship_cell_size, ship.bottom, ship_cell_size):
            pg.draw.line(screen, (200, 200, 200), (ship.left, y), (ship.right, y), 2)

def draw_canvas():
    pg.draw.rect(screen, (200, 200, 200), (side_margin, side_margin, screen_width - 2*side_margin, screen_height - 2*side_margin))
    draw_ships()

def draw_boundaries():
    #up down boundary line
    pg.draw.line(screen, (0, 0, 0), (side_margin, side_margin), (side_margin, screen_height-side_margin))
    
    #left right boundary line
    pg.draw.line(screen, (0, 0, 0), (side_margin, screen_height - side_margin), (screen_width - side_margin, screen_height - side_margin)) 


running = True
while running:
    for event in pg.event.get():
        if event.type == pg.QUIT:
            running = False
        elif event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
            lazer_state = not lazer_state
        elif event.type == pg.KEYDOWN and event.key == pg.K_r and dragging_ship is not None:
            candidate = pg.Rect(0, 0, dragging_ship.height, dragging_ship.width)
            candidate.center = dragging_ship.center
            candidate.clamp_ip(canvas_rect)
            if can_place_ship(dragging_ship, candidate):
                dragging_ship.update(candidate)
                mouse_x, mouse_y = pg.mouse.get_pos()
                drag_offset = (mouse_x - dragging_ship.x, mouse_y - dragging_ship.y)
        elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            if lazer_button.collidepoint(event.pos):
                lazer_state = not lazer_state
            elif input_a_box.collidepoint(event.pos):
                input_a_selected = not input_a_selected
                if input_a_selected:
                    input_b_selected = False
            elif input_b_box.collidepoint(event.pos):
                input_b_selected = not input_b_selected
                if input_b_selected:
                    input_a_selected = False
            else:
                for ship in reversed(ships):
                    if ship.collidepoint(event.pos):
                        dragging_ship = ship
                        drag_offset = (event.pos[0] - ship.x, event.pos[1] - ship.y)
                        break
        elif event.type == pg.MOUSEBUTTONUP and event.button == 1:
            dragging_ship = None
        elif event.type == pg.MOUSEMOTION and dragging_ship is not None:
            target = dragging_ship.copy()
            target.topleft = (event.pos[0] - drag_offset[0], event.pos[1] - drag_offset[1])
            target.clamp_ip(canvas_rect)

            candidate = dragging_ship.copy()
            candidate.x = target.x
            if can_place_ship(dragging_ship, candidate):
                dragging_ship.x = candidate.x

            candidate = dragging_ship.copy()
            candidate.y = target.y
            if can_place_ship(dragging_ship, candidate):
                dragging_ship.y = candidate.y
    screen.fill((255, 255, 255))

    handle_input()
    sidebar()
    draw_canvas()
    draw_boundaries()
    lazer_x = side_margin
    lazer_y = screen_height - side_margin - b
    lazer_angle = -a
    draw_lazer(lazer_x, lazer_y, lazer_angle)
    draw_lazerCannon(lazer_x, lazer_y, lazer_angle)

    pg.display.flip()

pg.quit()
