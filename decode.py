import sqlite3
import struct
import math
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter1d

# File path to the provided demo file
demo_file_path = 'demo.dm_84'

class ETPlayerMonitor:
    def __init__(self, demo_file):
        self.demo_file = demo_file
        self.weapon_usage = {}
        self.player_positions = {}
        self.aim_patterns = {}
        self.db_connection = None
        self.actions_buffer = []  # Buffer to store actions for batch insert
        self._initialize_database()

    def _initialize_database(self):
        # Setup SQLite database for persistent storage of parsed data
        self.db_connection = sqlite3.connect("player_data.db")
        cursor = self.db_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_actions (
                timestamp INTEGER,
                player_id INTEGER,
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
                file_size = f.seek(0, 2)
                f.seek(0)  # Reset to the start
                limit = int(file_size * 0.25)  # Parse first 25% of the file
                chunk_size = 3200  # Read larger chunks to reduce I/O operations

                while f.tell() < limit:
                    chunk = f.read(min(chunk_size, limit - f.tell()))
                    if not chunk:
                        break  # End of file
                    for i in range(0, len(chunk), 32):
                        packet = chunk[i:i+32]
                        if len(packet) < 32:
                            break  # Incomplete packet
                        self._process_packet(packet)
                
                # Insert any remaining actions in the buffer
                self._flush_actions_buffer()
        except Exception as e:
            print("Error parsing demo:", e)

    def _process_packet(self, packet):
        try:
            # Unpacking relevant fields (customized for demonstration purposes)
            data = struct.unpack("i" * 8, packet)  # Mock format, adjust as needed
            raw_timestamp, eType, eFlags, pos_x, pos_y, pos_z, angle_x, angle_y = data[:8]

            # Refine timestamp interpretation
            timestamp = self._convert_timestamp(raw_timestamp)

            # Extract and normalize data for interpretation
            player_id = self._extract_player_id(eFlags)
            self._interpret_position(timestamp, player_id, pos_x, pos_y, pos_z)
            self._interpret_angles(timestamp, player_id, angle_x, angle_y, 0)  # Assuming angle_z is unused in this demo
            self._interpret_weapon_usage(timestamp, player_id, eType, eFlags)
        except struct.error as e:
            print("Error in packet structure:", e)

    def _convert_timestamp(self, raw_timestamp):
        # Convert raw timestamp to milliseconds, assuming the raw value is in ticks
        # For example, assuming each tick is 1/20th of a second
        return raw_timestamp * 50  # 50 ms per tick

    def _extract_player_id(self, eFlags):
        # Extract player ID from eFlags using bitwise operations
        return (eFlags >> 16) & 0xFF  # Example: Extract bits 16-23 for player ID

    def _interpret_position(self, timestamp, player_id, pos_x, pos_y, pos_z):
        # Calculate movement details
        if player_id in self.player_positions:
            last_pos = self.player_positions[player_id]
            distance = math.sqrt((pos_x - last_pos[0]) ** 2 + (pos_y - last_pos[1]) ** 2 + (pos_z - last_pos[2]) ** 2)
            velocity = distance / (timestamp - last_pos[3]) if timestamp - last_pos[3] > 0 else 0
            self._store_action(timestamp, player_id, "move", None, pos_x, pos_y, pos_z, None, None, None, velocity, None)
        self.player_positions[player_id] = (pos_x, pos_y, pos_z, timestamp)

    def _interpret_angles(self, timestamp, player_id, angle_x, angle_y, angle_z):
        # Interpret aim direction and stability
        if player_id not in self.aim_patterns:
            self.aim_patterns[player_id] = []
        self.aim_patterns[player_id].append((angle_x, angle_y, angle_z, timestamp))

        # Check for unusual aim patterns (e.g., highly repetitive or precise)
        if len(self.aim_patterns[player_id]) >= 2:
            last_angle = self.aim_patterns[player_id][-2]
            angle_change = sum(abs(last_angle[i] - (angle_x, angle_y, angle_z)[i]) for i in range(3))
            if angle_change < 0.01:  # Threshold for aim consistency
                self._store_action(timestamp, player_id, "aim_consistency", None, None, None, None, angle_x, angle_y, angle_z, None, None)

    def _interpret_weapon_usage(self, timestamp, player_id, eType, eFlags):
        weapon = self._extract_weapon(eFlags)  # Replace with actual weapon decoding logic

        # Record firing, reloading, and other actions based on eType/eFlags
        if eType == 1:  # Assume 1 is a "fire" event
            if player_id not in self.weapon_usage:
                self.weapon_usage[player_id] = {"shots": 0, "hits": 0}
            self.weapon_usage[player_id]["shots"] += 1
            self._store_action(timestamp, player_id, "fire", weapon, None, None, None, None, None, None, None, None)

        elif eType == 2:  # Assume 2 is a "hit" event
            if player_id in self.weapon_usage:
                self.weapon_usage[player_id]["hits"] += 1
                accuracy = self.weapon_usage[player_id]["hits"] / self.weapon_usage[player_id]["shots"]
                self._store_action(timestamp, player_id, "hit", weapon, None, None, None, None, None, None, None, accuracy)

        elif eType == 3:  # Assume 3 is a "reload" event
            self._store_action(timestamp, player_id, "reload", weapon, None, None, None, None, None, None, None, None)

    def _extract_weapon(self, eFlags):
        # Extract weapon from eFlags using bitwise operations
        return (eFlags >> 8) & 0xFF  # Example: Extract bits 8-15 for weapon ID

    def _store_action(self, timestamp, player_id, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy):
        self.actions_buffer.append((timestamp, player_id, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy))
        if len(self.actions_buffer) >= 100:
            self._flush_actions_buffer()

    def _flush_actions_buffer(self):
        cursor = self.db_connection.cursor()
        cursor.executemany("""
            INSERT INTO player_actions (timestamp, player_id, action, weapon, pos_x, pos_y, pos_z, angle_x, angle_y, angle_z, velocity, accuracy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, self.actions_buffer)
        self.db_connection.commit()
        self.actions_buffer = []

    def close(self):
        if self.actions_buffer:
            self._flush_actions_buffer()
        if self.db_connection:
            self.db_connection.close()
        self._output_summary()

    def visualize_movement(self):
        # Extract positions for visualization
        player_id = 1  # Replace with actual player ID logic
        if player_id not in self.player_positions:
            print("No position data available for visualization.")
            return

        times = [pos[3] for pos in self.player_positions.values()]
        positions = np.array([pos[:3] for pos in self.player_positions.values()])

        # Smooth positions using Gaussian filter
        x_smooth = gaussian_filter1d(positions[:, 0], sigma=2)
        y_smooth = gaussian_filter1d(positions[:, 1], sigma=2)
        z_smooth = gaussian_filter1d(positions[:, 2], sigma=2)

        # Plot the smoothed movement in 2D
        plt.figure(figsize=(12, 8))
        plt.scatter(x_smooth, y_smooth, c=times, cmap='viridis', s=2)
        plt.colorbar(label='Time (ms)')
        plt.xlabel('X Position')
        plt.ylabel('Y Position')
        plt.title('Player Movement Over Time (Smoothed)')
        plt.show()

    def _output_summary(self):
        # Generate a summary of actions from the database
        cursor = self.db_connection.cursor()
        cursor.execute("SELECT action, COUNT(*) FROM player_actions GROUP BY action")
        summary = cursor.fetchall()

        print("\nSummary of Player Actions:")
        for action, count in summary:
            print(f"Action: {action}, Count: {count}")

# Instantiate the ETPlayerMonitor class and parse the demo
monitor = ETPlayerMonitor(demo_file_path)
monitor.parse_demo()
monitor.visualize_movement()
monitor.close()

# Displaying the database content for inspection
connection = sqlite3.connect("player_data.db") #should be just player_data.db
cursor = connection.cursor()
cursor.execute("SELECT * FROM player_actions LIMIT 10")
actions = cursor.fetchall()
connection.close()

print(actions)
