import aiosqlite
from typing import Optional
from config import DB_PATH
from models import ControllerProfile, ControllerTypeDefault, EmulatorConfig

SCHEMA_VERSION = 4

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS controllers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_id TEXT UNIQUE NOT NULL,
    default_name TEXT NOT NULL,
    custom_name TEXT,
    img_src TEXT DEFAULT 'default.png',
    snd_src TEXT DEFAULT 'default.mp3',
    vendor_id INTEGER,
    product_id INTEGER,
    guid_override TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS emulator_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emulator_name TEXT UNIQUE NOT NULL,
    config_path TEXT NOT NULL,
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS controller_type_defaults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name_pattern TEXT NOT NULL,
    img_src TEXT DEFAULT 'default.png',
    snd_src TEXT DEFAULT 'default.mp3',
    vendor_id INTEGER,
    product_id INTEGER,
    guid_override TEXT,
    UNIQUE(name_pattern, vendor_id, product_id)
);
"""

# Seed data: (name_pattern, img_src, snd_src, vendor_id, product_id, guid_override)
# guid_override: hardcoded SDL2 GUID for controllers where evdev GUID doesn't match
# (e.g. BT controllers where SDL2 uses HIDAPI and generates a different GUID)
SEED_TYPE_DEFAULTS = [
    ("Xbox Wireless Controller", "xbox-one.png", "xbox-one.mp3", 0x045E, 0x0B13, None),
    ("Xbox One Controller", "xbox-one.png", "xbox-one.mp3", 0x045E, 0x02EA, None),
    ("Xbox Controller", "xbox-one.png", "xbox-one.mp3", 0x045E, 0x0B12, None),
    ("Switch Pro Controller", "switch_pro.png", "switch.mp3", 0x057E, 0x2009, None),
    ("Joy-Con (L)", "joycon_l.png", "switch.mp3", 0x057E, 0x2006, None),
    ("Joy-Con (R)", "joycon_r.png", "switch.mp3", 0x057E, 0x2007, None),
    ("GameCube Controller Adapter", "gamecube.png", "switch_gamecube.mp3", 0x057E, 0x0337, None),
    # Lic Pro Controller: BT HID reports vendor=0/product=0, but SDL2 HIDAPI
    # identifies it as a Switch Pro Controller with this GUID
    ("Lic Pro Controller", "switch_gamecube.png", "switch_gamecube.mp3", None, None, "030000007e0500000920000000006806"),
    ("DualShock 4", "default.png", "default.mp3", 0x054C, 0x09CC, None),
    ("DualSense", "default.png", "default.mp3", 0x054C, 0x0CE6, None),
    ("SNES Controller", "snes.png", "snes.wav", 0x057E, 0x2017, None),
    ("8BitDo", "default.png", "default.mp3", None, None, None),
]

SEED_EMULATORS = [
    ("yuzu", "~/.var/app/org.yuzu_emu.yuzu/config/yuzu/qt-config.ini"),
]


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    """Initialize database with schema, run migrations, seed data."""
    db = await get_db()
    try:
        await _migrate(db)
    finally:
        await db.close()


async def _migrate(db: aiosqlite.Connection) -> None:
    """Handle schema creation and migration from old format."""
    # Check if old schema exists (has 'mac_address' column in controllers)
    old_schema = False
    try:
        cursor = await db.execute("PRAGMA table_info(controllers)")
        columns = await cursor.fetchall()
        col_names = [c[1] for c in columns]
        if "mac_address" in col_names and "unique_id" not in col_names:
            old_schema = True
    except Exception:
        pass

    if old_schema:
        await _migrate_from_old(db)
    else:
        # Check if tables need guid_override columns
        needs_type_rebuild = False
        needs_controller_guid = False

        try:
            cursor = await db.execute("PRAGMA table_info(controller_type_defaults)")
            columns = await cursor.fetchall()
            col_names = [c[1] for c in columns]
            if columns and "guid_override" not in col_names:
                needs_type_rebuild = True
        except Exception:
            pass

        try:
            cursor = await db.execute("PRAGMA table_info(controllers)")
            columns = await cursor.fetchall()
            col_names = [c[1] for c in columns]
            if columns and "guid_override" not in col_names:
                needs_controller_guid = True
        except Exception:
            pass

        if needs_type_rebuild:
            await db.execute("DROP TABLE IF EXISTS controller_type_defaults")

        await db.executescript(CREATE_TABLES)

        if needs_controller_guid:
            try:
                await db.execute("ALTER TABLE controllers ADD COLUMN guid_override TEXT")
            except Exception:
                pass

    # Check/set schema version
    cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    else:
        await db.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    # Seed type defaults
    for name_pattern, img_src, snd_src, vendor_id, product_id, guid_override in SEED_TYPE_DEFAULTS:
        await db.execute(
            "INSERT OR IGNORE INTO controller_type_defaults (name_pattern, img_src, snd_src, vendor_id, product_id, guid_override) VALUES (?, ?, ?, ?, ?, ?)",
            (name_pattern, img_src, snd_src, vendor_id, product_id, guid_override),
        )

    # Seed emulator configs
    import os
    for emu_name, config_path in SEED_EMULATORS:
        expanded = os.path.expanduser(config_path)
        await db.execute(
            "INSERT OR IGNORE INTO emulator_configs (emulator_name, config_path) VALUES (?, ?)",
            (emu_name, expanded),
        )

    await db.commit()


async def _migrate_from_old(db: aiosqlite.Connection) -> None:
    """Migrate from old schema (mac_address column) to new (unique_id)."""
    cursor = await db.execute("SELECT name, custom_name, mac_address, img_src FROM controllers")
    old_rows = await cursor.fetchall()

    await db.execute("DROP TABLE IF EXISTS controllers")
    await db.executescript(CREATE_TABLES)

    for row in old_rows:
        name = row[0]
        custom_name = row[1]
        mac_address = row[2]
        img_src = row[3]

        if mac_address and mac_address != "N/A":
            unique_id = mac_address
        else:
            continue

        await db.execute(
            "INSERT OR IGNORE INTO controllers (unique_id, default_name, custom_name, img_src) VALUES (?, ?, ?, ?)",
            (unique_id, name, custom_name, img_src or "default.png"),
        )

    await db.commit()


# --- CRUD operations ---

async def get_profile(unique_id: str) -> Optional[ControllerProfile]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT unique_id, default_name, custom_name, img_src, snd_src, vendor_id, product_id, guid_override FROM controllers WHERE unique_id = ?",
            (unique_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return ControllerProfile(
            unique_id=row[0],
            default_name=row[1],
            custom_name=row[2],
            img_src=row[3] or "default.png",
            snd_src=row[4] or "default.mp3",
            vendor_id=row[5],
            product_id=row[6],
            guid_override=row[7],
        )
    finally:
        await db.close()


async def upsert_profile(
    unique_id: str,
    default_name: str,
    vendor_id: Optional[int] = None,
    product_id: Optional[int] = None,
    img_src: Optional[str] = None,
    snd_src: Optional[str] = None,
) -> ControllerProfile:
    """Insert or update a controller profile. Returns the profile."""
    db = await get_db()
    try:
        existing = await db.execute(
            "SELECT id FROM controllers WHERE unique_id = ?", (unique_id,)
        )
        row = await existing.fetchone()

        if row:
            if vendor_id is not None:
                await db.execute(
                    "UPDATE controllers SET vendor_id = ?, updated_at = CURRENT_TIMESTAMP WHERE unique_id = ?",
                    (vendor_id, unique_id),
                )
            if product_id is not None:
                await db.execute(
                    "UPDATE controllers SET product_id = ?, updated_at = CURRENT_TIMESTAMP WHERE unique_id = ?",
                    (product_id, unique_id),
                )
        else:
            # Determine default assets and guid_override from type_defaults
            resolved_img = img_src or "default.png"
            resolved_snd = snd_src or "default.mp3"
            resolved_guid = None

            if not img_src or not snd_src:
                type_default = await get_type_default(default_name, vendor_id, product_id)
                if type_default:
                    resolved_img = img_src or type_default.img_src
                    resolved_snd = snd_src or type_default.snd_src
                    resolved_guid = type_default.guid_override

            await db.execute(
                "INSERT INTO controllers (unique_id, default_name, img_src, snd_src, vendor_id, product_id, guid_override) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (unique_id, default_name, resolved_img, resolved_snd, vendor_id, product_id, resolved_guid),
            )

        await db.commit()
    finally:
        await db.close()

    return (await get_profile(unique_id))  # type: ignore


async def update_profile_fields(
    unique_id: str,
    custom_name: Optional[str] = ...,
    img_src: Optional[str] = None,
    snd_src: Optional[str] = None,
    guid_override: Optional[str] = ...,
) -> Optional[ControllerProfile]:
    db = await get_db()
    try:
        sets = []
        params = []
        if custom_name is not ...:
            sets.append("custom_name = ?")
            params.append(custom_name)
        if img_src is not None:
            sets.append("img_src = ?")
            params.append(img_src)
        if snd_src is not None:
            sets.append("snd_src = ?")
            params.append(snd_src)
        if guid_override is not ...:
            sets.append("guid_override = ?")
            params.append(guid_override)

        if not sets:
            return await get_profile(unique_id)

        sets.append("updated_at = CURRENT_TIMESTAMP")
        params.append(unique_id)
        query = f"UPDATE controllers SET {', '.join(sets)} WHERE unique_id = ?"
        await db.execute(query, params)
        await db.commit()
    finally:
        await db.close()

    return await get_profile(unique_id)


async def get_all_profiles() -> list[ControllerProfile]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT unique_id, default_name, custom_name, img_src, snd_src, vendor_id, product_id, guid_override FROM controllers ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [
            ControllerProfile(
                unique_id=r[0],
                default_name=r[1],
                custom_name=r[2],
                img_src=r[3] or "default.png",
                snd_src=r[4] or "default.mp3",
                vendor_id=r[5],
                product_id=r[6],
                guid_override=r[7],
            )
            for r in rows
        ]
    finally:
        await db.close()


async def get_type_default(
    device_name: str,
    vendor_id: Optional[int] = None,
    product_id: Optional[int] = None,
) -> Optional[ControllerTypeDefault]:
    """Find a type default matching by vendor:product first, then by name pattern."""
    db = await get_db()
    try:
        # First try vendor:product match (most reliable)
        if vendor_id is not None and product_id is not None:
            cursor = await db.execute(
                "SELECT name_pattern, img_src, snd_src, vendor_id, product_id, guid_override FROM controller_type_defaults WHERE vendor_id = ? AND product_id = ?",
                (vendor_id, product_id),
            )
            row = await cursor.fetchone()
            if row:
                return ControllerTypeDefault(
                    name_pattern=row[0],
                    img_src=row[1] or "default.png",
                    snd_src=row[2] or "default.mp3",
                    vendor_id=row[3],
                    product_id=row[4],
                    guid_override=row[5],
                )

        # Fallback to name pattern matching
        cursor = await db.execute(
            "SELECT name_pattern, img_src, snd_src, vendor_id, product_id, guid_override FROM controller_type_defaults WHERE vendor_id IS NULL"
        )
        rows = await cursor.fetchall()
        for row in rows:
            if row[0].lower() in device_name.lower():
                return ControllerTypeDefault(
                    name_pattern=row[0],
                    img_src=row[1] or "default.png",
                    snd_src=row[2] or "default.mp3",
                    vendor_id=row[3],
                    product_id=row[4],
                    guid_override=row[5],
                )
        return None
    finally:
        await db.close()


async def get_all_emulator_configs() -> list[EmulatorConfig]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, emulator_name, config_path, enabled FROM emulator_configs ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [
            EmulatorConfig(id=r[0], emulator_name=r[1], config_path=r[2], enabled=bool(r[3]))
            for r in rows
        ]
    finally:
        await db.close()


async def update_emulator_config(
    emulator_name: str,
    config_path: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Optional[EmulatorConfig]:
    db = await get_db()
    try:
        sets = []
        params = []
        if config_path is not None:
            sets.append("config_path = ?")
            params.append(config_path)
        if enabled is not None:
            sets.append("enabled = ?")
            params.append(int(enabled))

        if not sets:
            return None

        params.append(emulator_name)
        query = f"UPDATE emulator_configs SET {', '.join(sets)} WHERE emulator_name = ?"
        await db.execute(query, params)
        await db.commit()

        cursor = await db.execute(
            "SELECT id, emulator_name, config_path, enabled FROM emulator_configs WHERE emulator_name = ?",
            (emulator_name,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return EmulatorConfig(id=row[0], emulator_name=row[1], config_path=row[2], enabled=bool(row[3]))
    finally:
        await db.close()
