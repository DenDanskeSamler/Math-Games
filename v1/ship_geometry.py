import math

class ShipGeometry:
    def __init__(
        self,
        ships,
        ship_angles,
        ships_left_dock,
        ship_tray_rect,
        canvas_rect,
        move_point_radius,
        rotate_widget_radius,
    ):
        self.ships = ships
        self.ship_angles = ship_angles
        self.ships_left_dock = ships_left_dock
        self.ship_tray_rect = ship_tray_rect
        self.canvas_rect = canvas_rect
        self.move_point_radius = move_point_radius
        self.rotate_widget_radius = rotate_widget_radius

    def can_place_ship(self, ship, candidate, candidate_angle=None):
        if candidate_angle is None:
            candidate_angle = self.ship_angles[id(ship)]
        if id(ship) in self.ships_left_dock and self.overlaps_ship_dock(
            candidate, candidate_angle
        ):
            return False
        return self.is_in_ship_area(candidate, candidate_angle) and all(
            other is ship
            or not self.ships_overlap(
                candidate,
                other,
                candidate_angle,
                self.ship_angles[id(other)],
            )
            for other in self.ships
        )

    def rotate_ship(self, ship, delta_degrees):
        current_angle = self.ship_angles[id(ship)]
        direction = 1 if delta_degrees > 0 else -1
        changed = False
        for _ in range(abs(int(delta_degrees))):
            candidate_angle = current_angle + math.radians(direction)
            candidate_angle = (candidate_angle + math.pi) % (2 * math.pi) - math.pi
            if not self.can_place_ship(ship, ship, candidate_angle):
                break
            current_angle = candidate_angle
            self.ship_angles[id(ship)] = current_angle
            self.mark_ship_left_dock(ship, current_angle)
            changed = True
        return changed

    def ship_bounds(self, ship, angle=None):
        if angle is None:
            angle = self.ship_angles[id(ship)]
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

    def overlaps_ship_dock(self, ship, angle=None):
        left, top, right, bottom = self.ship_bounds(ship, angle)
        return (
            left < self.ship_tray_rect.right
            and right > self.ship_tray_rect.left
            and top < self.ship_tray_rect.bottom
            and bottom > self.ship_tray_rect.top
        )

    def mark_ship_left_dock(self, ship, angle=None):
        if not self.overlaps_ship_dock(ship, angle):
            self.ships_left_dock.add(id(ship))

    def all_ships_left_dock(self):
        return all(
            not self.overlaps_ship_dock(ship, self.ship_angles[id(ship)])
            for ship in self.ships
        )

    def is_in_ship_area(self, ship, angle=None):
        left, top, right, bottom = self.ship_bounds(ship, angle)

        def inside(area):
            return (
                left >= area.left
                and top >= area.top
                and right <= area.right
                and bottom <= area.bottom
            )

        if inside(self.canvas_rect) or inside(self.ship_tray_rect):
            return True

        crosses_canvas_top = top < self.canvas_rect.top < bottom
        tray_board_left = max(
            self.canvas_rect.left, self.ship_tray_rect.left
        )
        tray_board_right = min(
            self.canvas_rect.right, self.ship_tray_rect.right
        )
        return (
            crosses_canvas_top
            and top >= self.ship_tray_rect.top
            and bottom <= self.canvas_rect.bottom
            and left >= tray_board_left
            and right <= tray_board_right
        )

    def ship_movement_points(self, ship):
        angle = self.ship_angles[id(ship)]
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

    def ship_rotate_center(self, ship):
        angle = self.ship_angles[id(ship)]
        local_y = ship.height / 2 + self.rotate_widget_radius + 2
        return (
            round(ship.centerx - local_y * math.sin(angle)),
            round(ship.centery + local_y * math.cos(angle)),
        )

    @staticmethod
    def point_in_circle(point, center, radius):
        return (
            (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2
            <= radius**2
        )

    @staticmethod
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

    @classmethod
    def minkowski_support(
        cls, first, second, direction, first_angle, second_angle
    ):
        first_point = cls.ellipse_support(first, direction, first_angle)
        second_point = cls.ellipse_support(
            second, (-direction[0], -direction[1]), second_angle
        )
        return first_point[0] - second_point[0], first_point[1] - second_point[1]

    @staticmethod
    def dot(first, second):
        return first[0] * second[0] + first[1] * second[1]

    @classmethod
    def triple_product(cls, first, second, third):
        return (
            second[0] * cls.dot(first, third)
            - first[0] * cls.dot(second, third),
            second[1] * cls.dot(first, third)
            - first[1] * cls.dot(second, third),
        )

    @classmethod
    def update_simplex(cls, simplex):
        point_a = simplex[-1]
        to_origin = (-point_a[0], -point_a[1])

        if len(simplex) == 2:
            point_b = simplex[-2]
            ab = (point_b[0] - point_a[0], point_b[1] - point_a[1])
            if cls.dot(ab, to_origin) > 0:
                direction = cls.triple_product(ab, to_origin, ab)
                if cls.dot(direction, direction) < 1e-12:
                    return True, (0, 0)
                return False, direction
            simplex[:] = [point_a]
            return False, to_origin

        point_b, point_c = simplex[-2], simplex[-3]
        ab = (point_b[0] - point_a[0], point_b[1] - point_a[1])
        ac = (point_c[0] - point_a[0], point_c[1] - point_a[1])
        if abs(ab[0] * ac[1] - ab[1] * ac[0]) < 1e-12:
            if cls.dot(ab, ab) >= cls.dot(ac, ac):
                simplex[:] = [point_b, point_a]
            else:
                simplex[:] = [point_c, point_a]
            return cls.update_simplex(simplex)

        ab_perpendicular = cls.triple_product(ac, ab, ab)
        if cls.dot(ab_perpendicular, to_origin) > 0:
            simplex[:] = [point_b, point_a]
            return False, ab_perpendicular

        ac_perpendicular = cls.triple_product(ab, ac, ac)
        if cls.dot(ac_perpendicular, to_origin) > 0:
            simplex[:] = [point_c, point_a]
            return False, ac_perpendicular

        return True, (0, 0)

    @classmethod
    def ships_overlap(cls, first, second, first_angle=0.0, second_angle=0.0):
        first_left, first_top, first_right, first_bottom = cls._bounds(
            first, first_angle
        )
        second_left, second_top, second_right, second_bottom = cls._bounds(
            second, second_angle
        )
        if (
            first_right <= second_left
            or second_right <= first_left
            or first_bottom <= second_top
            or second_bottom <= first_top
        ):
            return False
        direction = (
            second.centerx - first.centerx,
            second.centery - first.centery,
        )
        if direction == (0, 0):
            return True

        simplex = [
            cls.minkowski_support(
                first, second, direction, first_angle, second_angle
            )
        ]
        direction = (-simplex[0][0], -simplex[0][1])
        for _ in range(64):
            if cls.dot(direction, direction) < 1e-12:
                return True
            point = cls.minkowski_support(
                first, second, direction, first_angle, second_angle
            )
            if cls.dot(point, direction) <= 1e-10:
                return False
            if any(
                math.hypot(point[0] - previous[0], point[1] - previous[1])
                < 1e-10
                for previous in simplex
            ):
                return False
            simplex.append(point)
            overlaps, direction = cls.update_simplex(simplex)
            if overlaps:
                return True
        return True

    @staticmethod
    def _bounds(ship, angle):
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

    def point_inside_ship(self, ship, point):
        angle = self.ship_angles[id(ship)]
        delta_x = point[0] - ship.centerx
        delta_y = point[1] - ship.centery
        horizontal = (
            delta_x * math.cos(angle) + delta_y * math.sin(angle)
        ) / (ship.width / 2)
        vertical = (
            -delta_x * math.sin(angle) + delta_y * math.cos(angle)
        ) / (ship.height / 2)
        return horizontal**2 + vertical**2 <= 1
