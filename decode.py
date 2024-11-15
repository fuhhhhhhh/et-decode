import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter1d
import sqlite3
import struct
import math

# Importing the Huffman decoding logic from msg.c and huffman.c
from huffman import HuffmanTree, huffman_decode
from msg import MSG_ReadBits

MAX_WEAPONS = 64  # Defined MAX_WEAPONS based on the context provided

# Weapon table extracted from the provided .h/.c source files
WEAPON_TABLE = {
    0: "None",
    1: "Knife",
    2: "Luger",
    3: "Colt",
    4: "MP40",
    5: "Thompson",
    6: "Sten",
    7: "FG42",
    8: "Panzerfaust",
    9: "Flamethrower",
    10: "Grenade",
    11: "Grenade Launcher",
    12: "Mortar",
    13: "Dynamite",
    14: "Satchel Charge",
    15: "Airstrike Marker",
    16: "Landmine",
    17: "Smoke Grenade",
    18: "MG42",
    19: "Garand",
    20: "K43",
    21: "BAR",
    22: "M1 Carbine",
    23: "PPSH",
    24: "Panzerschreck",
    25: "Mosin-Nagant",
    26: "Unknown",
    27: "Unknown",
    28: "Unknown",
    29: "Unknown",
    30: "Unknown",
    31: "Unknown",
    32: "Unknown",
    33: "Unknown",
    34: "Unknown",
    35: "Unknown",
    36: "Unknown",
    37: "Unknown",
    38: "Unknown",
    39: "Unknown",
    40: "Unknown",
    41: "Unknown",
    42: "Unknown",
    43: "Unknown",
    44: "Unknown",
    45: "Unknown",
    46: "Unknown",
    47: "Unknown",
    48: "Unknown",
    49: "Unknown",
    50: "Unknown",
    51: "Unknown",
    52: "Unknown",
    53: "Unknown",
    54: "Unknown",
    55: "Unknown",
    56: "Unknown",
    57: "Unknown",
    58: "Unknown",
    59: "Unknown",
    60: "Unknown",
    61: "Unknown",
    62: "Unknown",
    63: "Unknown",
}

class ETPlayerMonitor:
    def __init__(self, demo_file):
        self.demo_file = demo_file
        self.weapon_usage = {}
        self.player_positions = {}
        self.aim_patterns = {}
        self.db_connection = None
        self.actions_buffer = []
        self.huffman_tree = HuffmanTree()  # Initialize HuffmanTree for decoding
        self._initialize_database()

    def _initialize_database(self):
        # Setup SQLite database for persistent storage of parsed data
        self.db_connection = sqlite3.connect("player_data.db")
        cursor = self.db_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_actions (
                timestamp INTEGER,
                player_id INTEGER,
                player_name TEXT,
                action TEXT,
                weapon INTEGER,
                pos_x REAL,
                pos_y REAL,
                pos_z REAL,
                angle_x REAL,
                angle_y REAL,
                angle_z REAL,
                velocity REAL,
                accuracy REAL
            )
        """)
        self.db_connection.commit()

    def parse_demo(self):
        try:
            with open(self.demo_file, "rb") as f:
                while packet := f.read(64):  # Adjusted buffer size to 64 bytes for proper unpacking
                    decoded_packet = self._huffman_decode(packet)
                    if decoded_packet:
                        self._process_packet(decoded_packet)
        except Exception as e:
            print("Error parsing demo:", e)

    def _huffman_decode(self, packet):
        try:
            return huffman_decode(self.huffman_tree, packet)
        except Exception as e:
            print("Error in Huffman decoding:", e)
            return None

    def _process_packet(self, packet):
        try:
            # Unpacking relevant fields (customized for demonstration purposes)
            data = struct.unpack("i" * 16, packet)  # Adjusted unpacking to match new buffer size
            timestamp, eType, eFlags, pos_x, pos_y, pos_z, angle_x, angle_y = data[:8]
            player_id = self._extract_player_id(eFlags)
            player_name = f"Player{player_id}"

            # Extract and normalize data for interpretation
            self._interpret_position(timestamp, player_id, player_name, pos_x, pos_y, pos_z)
            self._interpret_angles(timestamp, player_id, player_name, angle_x, angle_y, 0)  # Assuming angle_z is unused in this demo
            self._interpret_weapon_usage(timestamp, player_id, player_name, eType, eFlags)
        except struct.error as e:
            print("Error in packet structure:", e)

    def _interpret_position(self, timestamp, player_id, player_name, pos_x, pos_y, pos_z):
        # Calculate movement details
        if player_id in self.player_positions:
            last_pos = self.player_positions[player_id]
            distance = math.sqrt((pos_x - last_pos[0]) ** 2 + (pos_y - last_pos[1]) ** 2 + (pos_z - last_pos[2]) ** 2)
            velocity = distance / (timestamp - last_pos[3]) if timestamp - last_pos[3] > 0 else 0
            self._store_action(timestamp, player_id, player_name, "move", None, pos_x, pos_y, pos_z, None, None, None, velocity, None)
        self.player_positions[player_id] = (pos_x, pos_y, pos_z, timestamp)
    
    def _interpret_angles(self, timestamp, player_id, player_name, angle_x, angle_y, angle_z):
        # Interpret aim direction and stability
        if player_id not in self.aim_patterns:
            self.aim_patterns[player_id] = []
        self.aim_patterns[player_id].append((angle_x, angle_y, angle_z, timestamp))
        
        # Check for unusual aim patterns (e.g., highly repetitive or precise)
        if len(self.aim_patterns[player_id]) >= 2:
            last_angle = self.aim_patterns[player_id][-2]
            angle_change = sum(abs(last_angle[i] - (angle_x, angle_y, angle_z)[i]) for i in range(3))
            if angle_change < 0.01:  # Threshold for aim consistency
                self._store_action(timestamp, player_id, player_name, "aim_consistency", None, None, None, None, angle_x, angle_y, angle_z, None, None)
    
    def _interpret_weapon_usage(self, timestamp, player_id, player_name, eType, eFlags):
        weapon = self._extract_weapon(eFlags)
        if weapon == 0:
            # Ignore if weapon ID extraction failed
            return

        # Record firing, reloading, and other actions based on eType/eFlags
        if eType == 1:
            # Check for valid weapon and ensure the event represents a firing action
            if weapon != 0 and player_id in self.weapon_usage:
                self.weapon_usage[player_id]["shots"] += 1
                self._store_action(timestamp, player_id, player_name, "fire", weapon, None, None, None, None, None, None, None, None)

        elif eType == 2:  # Assume 2 is a "hit" event
            if player_id in self.weapon_usage:
                self.weapon_usage[player_id]["hits"] += 1
                accuracy = self.weapon_usage[player_id]["hits"] / self.weapon_usage[player_id]["shots"]
                self._store_action(timestamp, player_id, player_name, "hit", weapon, None, None, None, None, None, None, None, accuracy)

        elif eType == 3:  # Assume 3 is a "reload" event
            self._store_action(timestamp, player_id, player_name, "reload", weapon, None, None, None, None, None, None, None, None)

    def _extract_weapon(self, eFlags):
        # Extract weapon from eFlags using bitwise operations
        weapon_id = (eFlags >> 8) & 0xFF  # Extract bits 8-15 for weapon ID
        # Ensure weapon ID is within a valid range
        if weapon_id < 0 or weapon_id >= MAX_WEAPONS:
            print(f"Warning: Invalid weapon ID extracted: {weapon_id}")
        else:
            print(f"Debug: Extracted valid weapon ID: {weapon_id} ({WEAPON_TABLE.get(weapon_id, 'Unknown')})")
        return weapon_id if weapon_id >= 0 and weapon_id < MAX_WEAPONS else 0

    def _extract_player_id(self, eFlags):
        # Example extraction logic for player ID from eFlags (adjust as needed)
        return (eFlags >> 16) & 0xFF

    def _store_action(self, timestamp, player_id, player_name, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy):
        self.actions_buffer.append((timestamp, player_id, player_name, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy))
        if len(self.actions_buffer) >= 100:
            self._flush_actions_buffer()

    def _flush_actions_buffer(self):
        cursor = self.db_connection.cursor()
        cursor.executemany("""
            INSERT INTO player_actions (timestamp, player_id, player_name, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, self.actions_buffer)
        self.db_connection.commit()
        self.actions_buffer = []

    def close(self):
        if self.actions_buffer:
            self._flush_actions_buffer()
        self._output_summary()
        if self.db_connection:
            self.db_connection.close()

    def visualize_movement(self):
        # Extract positions for visualization
        paths = {player_id: [] for player_id in self.player_positions}
        for player_id, (pos_x, pos_y, _, _) in self.player_positions.items():
            paths[player_id].append((pos_x, pos_y))

        if not any(paths.values()):
            print("No position data available for visualization.")
            return

        # Plot the paths for each player using arrows and scatter plots for events
        plt.figure(figsize=(12, 8))
        for player_id, player_positions in paths.items():
            if len(player_positions) > 1:
                x_positions, y_positions = zip(*player_positions)
                plt.quiver(x_positions[:-1], y_positions[:-1],
                           np.diff(x_positions), np.diff(y_positions),
                           angles='xy', scale_units='xy', scale=1,
                           label=f"Player {player_id}", alpha=0.6)
                plt.scatter(x_positions, y_positions, s=5)  # Mark positions with small dots

        plt.xlabel('X Position')
        plt.ylabel('Y Position')
        plt.title('Player Movement Paths')
        plt.legend()
        plt.grid(True)
        plt.show()

    def _output_summary(self):
        # Generate a summary of actions from the database
        cursor = self.db_connection.cursor()
        cursor.execute("SELECT player_name, action, COUNT(*) FROM player_actions GROUP BY player_name, action")
        summary = cursor.fetchall()

        print("\nSummary of Player Actions:")
        for player_name, action, count in summary:
            print(f"Player: {player_name}, Action: {action}, Count: {count}")

# Instantiate the ETPlayerMonitor class and parse the demo
demo_file_path = 'demo.dm_84'  # Update with the correct path to your demo file
monitor = ETPlayerMonitor(demo_file_path)
monitor.parse_demo()
monitor.visualize_movement()
monitor.close()

# Displaying the database content for inspection
connection = sqlite3.connect("player_data.db") # Updated database path
cursor = connection.cursor()
cursor.execute("SELECT * FROM player_actions LIMIT 10")
actions = cursor.fetchall()
connection.close()

print(actions)
