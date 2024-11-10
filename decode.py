import sqlite3
import struct
from ctypes import Structure, c_int, c_float
from enum import IntEnum
import math

# Constants
MAX_INT32 = 2**31 - 1
MIN_INT32 = -2**31

# Enums and Structs aligned with q_shared.h

class EntityType(IntEnum):
    ET_GENERAL = 0
    ET_PLAYER = 1
    ET_ITEM = 2
    ET_MISSILE = 3
    ET_MOVER = 4
    ET_BEAM = 5
    ET_PORTAL = 6
    ET_SPEAKER = 7
    ET_TELEPORT_TRIGGER = 9
    ET_INVISIBLE = 10
    ET_OID_TRIGGER = 12
    ET_EXPLOSIVE_INDICATOR = 13
    ET_EXPLOSIVE = 14
    # Add other types as needed

class TrajectoryType(IntEnum):
    TR_STATIONARY = 0
    TR_INTERPOLATE = 1
    TR_LINEAR = 2
    TR_LINEAR_STOP = 3
    TR_SINE = 4
    TR_GRAVITY = 5
    # Add other trajectory types as needed

class Vec3(Structure):
    _fields_ = [("x", c_float), ("y", c_float), ("z", c_float)]

class Trajectory(Structure):
    _fields_ = [
        ("trType", c_int),
        ("trTime", c_int),
        ("trDuration", c_int),
        ("trBase", Vec3),
        ("trDelta", Vec3)
    ]

class EntityState(Structure):
    _fields_ = [
        ("number", c_int),
        ("eType", c_int),
        ("eFlags", c_int),
        ("pos", Trajectory),
        ("apos", Trajectory),
        ("time", c_int),
        ("time2", c_int),
        ("origin", Vec3),
        ("origin2", Vec3),
        ("angles", Vec3),
        ("angles2", Vec3)
    ]

# Helper functions

def initialize_database(db_name='demo_data.db'):
    """Initializes the database with a table for storing entity states."""
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("DROP TABLE IF EXISTS entity_states")
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS entity_states (
                        number INTEGER,
                        eType INTEGER,
                        eFlags INTEGER,
                        pos_trType INTEGER,
                        pos_trTime INTEGER,
                        pos_trDuration INTEGER,
                        pos_trBase_x REAL, pos_trBase_y REAL, pos_trBase_z REAL,
                        pos_trDelta_x REAL, pos_trDelta_y REAL, pos_trDelta_z REAL,
                        apos_trType INTEGER,
                        apos_trTime INTEGER,
                        apos_trDuration INTEGER,
                        apos_trBase_x REAL, apos_trBase_y REAL, apos_trBase_z REAL,
                        apos_trDelta_x REAL, apos_trDelta_y REAL, apos_trDelta_z REAL,
                        time INTEGER,
                        time2 INTEGER,
                        origin_x REAL, origin_y REAL, origin_z REAL,
                        origin2_x REAL, origin2_y REAL, origin2_z REAL,
                        angles_x REAL, angles_y REAL, angles_z REAL,
                        angles2_x REAL, angles2_y REAL, angles2_z REAL
                    )''')  
    conn.commit()
    conn.close()

def sanitize_value(value):
    """Sanitize NaN and Infinity values, replacing them with predefined limits."""
    if isinstance(value, float):
        if math.isnan(value) or value == float('inf') or value == float('-inf'):
            return 0.0
        else:
            return max(MIN_INT32, min(MAX_INT32, value))
    return value

def parse_dm84_file(file_path):
    """Parses the .dm_84 demo file and extracts entity states."""
    entity_states = []
    packet_size = struct.calcsize('<iiii9f9fiiiiiiiii9f9f')  # Assuming this is the correct size, adjust if necessary

    with open(file_path, 'rb') as f:
        while True:
            packet = f.read(packet_size)
            if not packet:
                break
            
            if len(packet) != packet_size:
                print(f"Warning: Packet size mismatch. Expected {packet_size} bytes, but got {len(packet)} bytes.")
                continue
            
            unpacked_data = struct.unpack('<iiii9f9fiiiiiiiii9f9f', packet)
            
            # Sanitize and ensure data types are correct
            sanitized_data = [sanitize_value(val) if val is not None else None for val in unpacked_data]
            
            # Initialize entity state with sanitized data
            entity_state = EntityState(
                number=int(sanitized_data[0]),  
                eType=int(sanitized_data[1]),
                eFlags=int(sanitized_data[2]),
                pos=Trajectory(
                    trType=int(sanitized_data[3]),
                    trTime=int(sanitized_data[4]),
                    trDuration=int(sanitized_data[5]),
                    trBase=Vec3(float(sanitized_data[6] or 0), float(sanitized_data[7] or 0), float(sanitized_data[8] or 0)),
                    trDelta=Vec3(float(sanitized_data[9] or 0), float(sanitized_data[10] or 0), float(sanitized_data[11] or 0))
                ),
                apos=Trajectory(
                    trType=int(sanitized_data[12]),
                    trTime=int(sanitized_data[13]),
                    trDuration=int(sanitized_data[14]),
                    trBase=Vec3(float(sanitized_data[15] or 0), float(sanitized_data[16] or 0), float(sanitized_data[17] or 0)),
                    trDelta=Vec3(float(sanitized_data[18] or 0), float(sanitized_data[19] or 0), float(sanitized_data[20] or 0))
                ),
                time=int(sanitized_data[21] or 0),
                time2=int(sanitized_data[22] or 0),
                origin=Vec3(float(sanitized_data[23] or 0), float(sanitized_data[24] or 0), float(sanitized_data[25] or 0)),
                origin2=Vec3(float(sanitized_data[26] or 0), float(sanitized_data[27] or 0), float(sanitized_data[28] or 0)),
                angles=Vec3(float(sanitized_data[29] or 0), float(sanitized_data[30] or 0), float(sanitized_data[31] or 0)),
                angles2=Vec3(float(sanitized_data[32] or 0), float(sanitized_data[33] or 0), float(sanitized_data[34] or 0))
            )
            entity_states.append(entity_state)

    return entity_states

def save_entity_state_to_db(entity_state, db_name='demo_data.db'):
    """Saves an EntityState instance to the SQLite database with dynamic handling of missing values."""
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # Extract the non-None fields and their values
    fields = []
    values = []

    for field_tuple in EntityState._fields_:
        field_name = field_tuple[0]  # Extract the field name
        field_value = getattr(entity_state, field_name)
        
        if isinstance(field_value, Trajectory):
            # Unpack Trajectory fields into individual components if the Trajectory object is not None
            if field_value is not None:
                fields.extend([f"{field_name}_trType", f"{field_name}_trTime", f"{field_name}_trDuration",
                               f"{field_name}_trBase_x", f"{field_name}_trBase_y", f"{field_name}_trBase_z",
                               f"{field_name}_trDelta_x", f"{field_name}_trDelta_y", f"{field_name}_trDelta_z"])
                values.extend([field_value.trType, field_value.trTime, field_value.trDuration,
                               field_value.trBase.x, field_value.trBase.y, field_value.trBase.z,
                               field_value.trDelta.x, field_value.trDelta.y, field_value.trDelta.z])
        elif isinstance(field_value, Vec3):
            # Unpack Vec3 fields into individual components
            if field_value is not None:
                fields.extend([f"{field_name}_x", f"{field_name}_y", f"{field_name}_z"])
                values.extend([field_value.x, field_value.y, field_value.z])
        elif field_value is not None:
            fields.append(field_name)
            values.append(field_value)

    # Construct the dynamic SQL query based on available fields
    query = f"INSERT INTO entity_states ({', '.join(fields)}) VALUES ({', '.join(['?'] * len(values))})"
    
    try:
        cursor.execute(query, values)
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"SQL Error: {e}")
        print("Query:", query)
        print("Values:", values)
    finally:
        conn.close()

def process_demo_file(file_path, db_name='demo_data.db'):
    """Processes the demo file, parses entity states, and stores them in the database."""
    initialize_database(db_name)  # Set up the database
    entity_states = parse_dm84_file(file_path)
    for entity_state in entity_states:
        save_entity_state_to_db(entity_state, db_name)
    print(f"Processed and saved {len(entity_states)} entity states to the database.")

# Run the solution
demo_file_path = 'demo.dm_84'  # Path to your .dm_84 demo file
process_demo_file(demo_file_path)
