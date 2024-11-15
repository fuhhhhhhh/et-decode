import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter1d
import sqlite3
import struct
import math
import ctypes
import os

# Load Huffman DLL using ctypes
huffman_dll_path = "C:\\Users\\root\\Desktop\\et-decode\\huffman.dll"
huffman = ctypes.CDLL(huffman_dll_path)

# Define function prototypes for huffman.dll
huffman.huffman_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
huffman.huffman_decode.restype = ctypes.c_int

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
        """
        )
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
            input_buffer = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
            output_buffer = (ctypes.c_ubyte * 1024)()  # Assuming max output size is 1024 bytes
            result = huffman.huffman_decode(ctypes.byref(input_buffer), ctypes.byref(output_buffer))
            if result < 0:
                raise ValueError("Huffman decoding failed")
            return bytes(output_buffer[:result])
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
        weapon_id = (eFlags >> 8) & 0xFF  # Example bitwise extraction
        return WEAPON_TABLE.get(weapon_id, "Unknown")

    def _extract_player_id(self, eFlags):
        # Extract player ID from eFlags using bitwise operations
        return eFlags & 0xFF  # Example bitwise extraction

    def _store_action(self, timestamp, player_id, player_name, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy):
        cursor = self.db_connection.cursor()
        cursor.execute("""
            INSERT INTO player_actions (timestamp, player_id, player_name, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, player_id, player_name, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy))
        self.db_connection.commit()

    def plot_player_data(self, player_id):
        cursor = self.db_connection.cursor()
        cursor.execute("SELECT * FROM player_actions WHERE player_id = ?", (player_id,))
        rows = cursor.fetchall()

        timestamps, pos_x, pos_y, pos_z = [], [], [], []
        for row in rows:
            timestamps.append(row[0])
            pos_x.append(row[5])
            pos_y.append(row[6])
            pos_z.append(row[7])

        pos_x_smooth = gaussian_filter1d(pos_x, sigma=2)
        pos_y_smooth = gaussian_filter1d(pos_y, sigma=2)
        pos_z_smooth = gaussian_filter1d(pos_z, sigma=2)

        plt.plot(timestamps, pos_x_smooth, label="Position X")
        plt.plot(timestamps, pos_y_smooth, label="Position Y")
        plt.plot(timestamps, pos_z_smooth, label="Position Z")
        plt.xlabel("Timestamp")
        plt.ylabel("Position")
        plt.title(f"Player {player_id} Movement Data")
        plt.legend()
        plt.show()

# Example usage
if __name__ == "__main__":
    demo_file = "demo.dm_84"
    et_monitor = ETPlayerMonitor(demo_file)
    et_monitor.parse_demo()
    et_monitor.plot_player_data(0)
