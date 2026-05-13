"""Chinese Checkers game logic with long jump (catapult) support."""

from __future__ import annotations
from collections import deque

# Six hex directions as (row_delta, col_delta)
DIRECTIONS = [
    (0, -2),   # Left
    (0, 2),    # Right
    (-1, -1),  # Upper-left
    (-1, 1),   # Upper-right
    (1, -1),   # Lower-left
    (1, 1),    # Lower-right
]

# Row definitions: each row's valid column values
# Columns use a grid where adjacent positions in the same row differ by 2,
# and adjacent rows' positions differ by 1 in column value.
ROW_COLS: dict[int, list[int]] = {
    0:  [12],
    1:  [11, 13],
    2:  [10, 12, 14],
    3:  [9, 11, 13, 15],
    4:  list(range(0, 25, 2)),     # 13 positions
    5:  list(range(1, 24, 2)),     # 12 positions
    6:  list(range(2, 23, 2)),     # 11 positions
    7:  list(range(3, 22, 2)),     # 10 positions
    8:  list(range(4, 21, 2)),     # 9 positions
    9:  list(range(3, 22, 2)),     # 10 positions
    10: list(range(2, 23, 2)),     # 11 positions
    11: list(range(1, 24, 2)),     # 12 positions
    12: list(range(0, 25, 2)),     # 13 positions
    13: [9, 11, 13, 15],
    14: [10, 12, 14],
    15: [11, 13],
    16: [12],
}

# All valid positions as a set of (row, col) tuples
ALL_POSITIONS: set[tuple[int, int]] = set()
for r, cols in ROW_COLS.items():
    for c in cols:
        ALL_POSITIONS.add((r, c))

assert len(ALL_POSITIONS) == 121

# Home triangles for each player slot (0-5)
# Triangle 0: top (rows 0-3)
# Triangle 1: upper-right (right side of rows 4-7)
# Triangle 2: lower-right (right side of rows 9-12)
# Triangle 3: bottom (rows 13-16)
# Triangle 4: lower-left (left side of rows 9-12)
# Triangle 5: upper-left (left side of rows 4-7)

HOME_TRIANGLES: dict[int, list[tuple[int, int]]] = {
    0: [],  # top
    1: [],  # upper-right
    2: [],  # lower-right
    3: [],  # bottom
    4: [],  # lower-left
    5: [],  # upper-left
}

# Triangle 0 (top): all positions in rows 0-3
for r in range(0, 4):
    for c in ROW_COLS[r]:
        HOME_TRIANGLES[0].append((r, c))

# Triangle 3 (bottom): all positions in rows 13-16
for r in range(13, 17):
    for c in ROW_COLS[r]:
        HOME_TRIANGLES[3].append((r, c))

# Triangle 5 (upper-left): leftmost positions in rows 4-7
_left_counts = {4: 4, 5: 3, 6: 2, 7: 1}
for r, count in _left_counts.items():
    for c in ROW_COLS[r][:count]:
        HOME_TRIANGLES[5].append((r, c))

# Triangle 1 (upper-right): rightmost positions in rows 4-7
for r, count in _left_counts.items():
    for c in ROW_COLS[r][-count:]:
        HOME_TRIANGLES[1].append((r, c))

# Triangle 4 (lower-left): leftmost positions in rows 9-12
_left_counts_lower = {9: 1, 10: 2, 11: 3, 12: 4}
for r, count in _left_counts_lower.items():
    for c in ROW_COLS[r][:count]:
        HOME_TRIANGLES[4].append((r, c))

# Triangle 2 (lower-right): rightmost positions in rows 9-12
for r, count in _left_counts_lower.items():
    for c in ROW_COLS[r][-count:]:
        HOME_TRIANGLES[2].append((r, c))

# Verify each triangle has 10 positions
for tri_id, positions in HOME_TRIANGLES.items():
    assert len(positions) == 10, f"Triangle {tri_id} has {len(positions)} positions"

# Opposite triangles: 0↔3, 1↔4, 2↔5
OPPOSITE_TRIANGLE = {0: 3, 3: 0, 1: 4, 4: 1, 2: 5, 5: 2}

# Player slot assignments by player count
SLOT_ASSIGNMENTS = {
    2: [0, 3],
    3: [0, 2, 4],
    4: [0, 1, 3, 4],
    6: [0, 1, 2, 3, 4, 5],
}

# Colors for each slot
SLOT_COLORS = {
    0: "red",
    1: "blue",
    2: "green",
    3: "yellow",
    4: "purple",
    5: "orange",
}


class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        self.password: str | None = None
        self.players: list[dict] = []  # [{"name": str, "id": str, "slot": int | None}]
        self.host_id: str | None = None
        self.phase: str = "idle"  # idle, lobby, playing, finished
        self.board: dict[tuple[int, int], int | None] = {}  # pos -> slot or None
        self.current_turn_index: int = 0  # index into self.players
        self.winner: int | None = None
        self.disconnected: set[str] = set()  # player IDs that disconnected

    def create(self, name: str, player_id: str, password: str):
        self.reset()
        self.password = password
        self.host_id = player_id
        self.phase = "lobby"
        self.players.append({"name": name, "id": player_id, "slot": None})

    def join(self, name: str, player_id: str, password: str) -> int:
        """Join the game. Returns the player index."""
        if self.phase != "lobby":
            raise ValueError("Game is not in lobby phase")
        if self.password != password:
            raise ValueError("Wrong password")
        if len(self.players) >= 6:
            raise ValueError("Game is full")
        for p in self.players:
            if p["id"] == player_id:
                raise ValueError("Already in the game")
        idx = len(self.players)
        self.players.append({"name": name, "id": player_id, "slot": None})
        return idx

    def start(self, host_id: str):
        """Start the game. Only the host can do this."""
        if self.phase != "lobby":
            raise ValueError("Game is not in lobby phase")
        if host_id != self.host_id:
            raise ValueError("Only the host can start the game")

        n = len(self.players)
        if n not in SLOT_ASSIGNMENTS:
            raise ValueError(f"Need 2, 3, 4, or 6 players to start (currently {n})")

        slots = SLOT_ASSIGNMENTS[n]
        for i, player in enumerate(self.players):
            player["slot"] = slots[i]

        # Initialize board
        self.board = {pos: None for pos in ALL_POSITIONS}
        for player in self.players:
            slot = player["slot"]
            for pos in HOME_TRIANGLES[slot]:
                self.board[pos] = slot

        self.current_turn_index = 0
        self.phase = "playing"

    def get_current_player(self) -> dict | None:
        if self.phase != "playing":
            return None
        return self.players[self.current_turn_index]

    def get_valid_moves(self, pos: tuple[int, int], player_id: str) -> list[tuple[int, int]]:
        """Get all valid destination positions for a piece at pos."""
        if self.phase != "playing":
            return []

        current = self.get_current_player()
        if not current or current["id"] != player_id:
            return []

        slot = current["slot"]
        if self.board.get(pos) != slot:
            return []

        moves = set()

        # Single step moves to adjacent empty positions
        for dr, dc in DIRECTIONS:
            nr, nc = pos[0] + dr, pos[1] + dc
            neighbor = (nr, nc)
            if neighbor in ALL_POSITIONS and self.board[neighbor] is None:
                moves.add(neighbor)

        # Long jump / catapult moves (BFS for chain jumps)
        visited = {pos}
        queue = deque([pos])
        while queue:
            current_pos = queue.popleft()
            for dr, dc in DIRECTIONS:
                landing = self._try_long_jump(current_pos, dr, dc)
                if landing and landing not in visited:
                    visited.add(landing)
                    moves.add(landing)
                    queue.append(landing)

        return sorted(moves)

    def _try_long_jump(self, pos: tuple[int, int], dr: int, dc: int) -> tuple[int, int] | None:
        """Try a long jump from pos in direction (dr, dc).

        A long jump works like this:
        1. Walk from pos in the given direction
        2. Find the first occupied position (the pivot) at distance d
        3. All positions between pos and pivot must be empty
        4. Continue d more steps past the pivot
        5. All positions between pivot and landing must be empty
        6. The landing position must be empty and valid
        """
        r, c = pos
        distance = 0

        # Walk until we find a piece
        while True:
            r += dr
            c += dc
            if (r, c) not in ALL_POSITIONS:
                return None
            distance += 1
            if self.board[(r, c)] is not None:
                # Found the pivot piece
                break
            # Position is empty, keep walking

        # Continue the same distance past the pivot
        for _ in range(distance):
            r += dr
            c += dc
            if (r, c) not in ALL_POSITIONS:
                return None
            if self.board[(r, c)] is not None:
                return None  # Blocked

        return (r, c)

    def make_move(self, from_pos: tuple[int, int], to_pos: tuple[int, int], player_id: str) -> dict:
        """Execute a move. Returns result dict."""
        if self.phase != "playing":
            raise ValueError("Game is not in progress")

        current = self.get_current_player()
        if not current or current["id"] != player_id:
            raise ValueError("Not your turn")

        slot = current["slot"]
        if self.board.get(from_pos) != slot:
            raise ValueError("Not your piece")

        valid = self.get_valid_moves(from_pos, player_id)
        if to_pos not in valid:
            raise ValueError("Invalid move")

        # Execute
        self.board[from_pos] = None
        self.board[to_pos] = slot

        # Check win condition
        goal_triangle = OPPOSITE_TRIANGLE[slot]
        goal_positions = HOME_TRIANGLES[goal_triangle]
        won = all(self.board[pos] == slot for pos in goal_positions)

        if won:
            self.phase = "finished"
            self.winner = self.current_turn_index
            return {
                "from": from_pos,
                "to": to_pos,
                "player_index": self.current_turn_index,
                "slot": slot,
                "winner": self.current_turn_index,
            }

        # Advance turn (skip disconnected players)
        self._advance_turn()

        return {
            "from": from_pos,
            "to": to_pos,
            "player_index": self.current_turn_index,
            "slot": slot,
            "next_turn": self.current_turn_index,
        }

    def _advance_turn(self):
        """Advance to the next connected player's turn."""
        n = len(self.players)
        for _ in range(n):
            self.current_turn_index = (self.current_turn_index + 1) % n
            if self.players[self.current_turn_index]["id"] not in self.disconnected:
                return
        # All players disconnected — shouldn't happen in practice

    def remove_player(self, player_id: str):
        """Handle a player disconnecting."""
        self.disconnected.add(player_id)
        if self.phase == "playing":
            # If it was their turn, advance
            current = self.get_current_player()
            if current and current["id"] == player_id:
                self._advance_turn()

            # Check if only one player left
            active = [p for p in self.players if p["id"] not in self.disconnected]
            if len(active) <= 1 and active:
                self.phase = "finished"
                self.winner = self.players.index(active[0])

    def get_state(self) -> dict:
        """Get full game state for sending to clients."""
        board_data = {}
        if self.board:
            for pos, slot in self.board.items():
                if slot is not None:
                    board_data[f"{pos[0]},{pos[1]}"] = slot

        return {
            "phase": self.phase,
            "players": [
                {"name": p["name"], "slot": p["slot"],
                 "connected": p["id"] not in self.disconnected}
                for p in self.players
            ],
            "board": board_data,
            "current_turn": self.current_turn_index,
            "winner": self.winner,
        }

    def get_board_definition(self) -> dict:
        """Get static board definition (positions, triangles, etc.)."""
        positions = [[r, c] for r, c in sorted(ALL_POSITIONS)]
        triangles = {
            str(slot): [[r, c] for r, c in positions_list]
            for slot, positions_list in HOME_TRIANGLES.items()
        }
        return {
            "positions": positions,
            "triangles": triangles,
            "slot_colors": SLOT_COLORS,
            "opposite": {str(k): v for k, v in OPPOSITE_TRIANGLE.items()},
        }
