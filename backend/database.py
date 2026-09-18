import aiosqlite
from typing import Optional
from config import DB_PATH
from models import ControllerProfile, ControllerTypeDefault, EmulatorConfig

SCHEMA_VERSION = 6

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
    bluetooth_address TEXT,
    tr2_is_start INTEGER DEFAULT 0,
    start_button_override INTEGER,
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
    start_button INTEGER,
    UNIQUE(name_pattern, vendor_id, product_id)
);
"""

# Seed data: (name_pattern, img_src, snd_src, vendor_id, product_id, guid_override, start_button)
_BTN_START = 315
_BTN_TR2 = 313
# Wii Remote's "+" button reports as KEY_NEXT, not a conventional gamepad button code.
_KEY_NEXT = 407
# A solo Joy-Con (L) has no "+" (Start) button - its "-" reports as BTN_SELECT,
# used here as the "ready" gesture in its place.
_BTN_SELECT = 314
SEED_TYPE_DEFAULTS = [
    ("Xbox Wireless Controller", "xbox-one.png", "xbox-one.mp3", 0x045E, 0x0B13, None, None),
    ("Xbox One Controller", "xbox-one.png", "xbox-one.mp3", 0x045E, 0x02EA, None, None),
    ("Xbox Controller", "xbox-one.png", "xbox-one.mp3", 0x045E, 0x0B12, None, None),
    ("Switch Pro Controller", "switch_pro.png", "switch.mp3", 0x057E, 0x2009, None, None),
    ("Joy-Con (L)", "joycon_l.png", "switch.mp3", 0x057E, 0x2006, None, _BTN_SELECT),
    ("Joy-Con (R)", "joycon_r.png", "switch.mp3", 0x057E, 0x2007, None, None),
    ("Joy-Con (L+R)", "joycon_l.png", "switch.mp3", None, None, None, None),
    ("GameCube Controller Adapter", "gamecube.png", "switch_gamecube.mp3", 0x057E, 0x0337, None, None),
    ("Lic Pro Controller", "switch_gamecube.png", "switch_gamecube.mp3", None, None, "030000007e0500000920000000006806", _BTN_TR2),
    ("DualShock 4", "default.png", "default.mp3", 0x054C, 0x09CC, None, None),
    ("DualSense", "default.png", "default.mp3", 0x054C, 0x0CE6, None, None),
    ("SNES Controller", "snes.png", "snes.wav", 0x057E, 0x2017, None, _BTN_TR2),
    # Generic USB/wireless-dongle SNES pads (DragonRise clones): Start emits BTN_TR2
    ("SNES Controller (USB)", "snes.png", "snes.wav", 0x0079, 0x0126, None, _BTN_TR2),
    ("8BitDo", "default.png", "default.mp3", None, None, None, None),
    ("Nintendo Wii Remote", "default.png", "default.mp3", 0x057E, 0x0306, None, _KEY_NEXT),
]

SEED_EMULATORS = [
    ("yuzu", "~/.var/app/org.yuzu_emu.yuzu/config/yuzu/qt-config.ini"),
    ("eden", "~/.config/eden/qt-config.ini"),
    ("dolphin_gc", "~/.var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/GCPadNew.ini"),
    ("dolphin_wii", "~/.var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/WiimoteNew.ini"),
    ("desmume", "~/.var/app/org.desmume.DeSmuME/config/desmume/config.cfg"),
    ("mesen", "~/.local/share/mesen/settings.json"),
    ("parallel", "~/.config/parallel-launcher/settings.cfg"),
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

        needs_type_start_button = False
        try:
            cursor = await db.execute("PRAGMA table_info(controller_type_defaults)")
            columns = await cursor.fetchall()
            col_names = [c[1] for c in columns]
            if columns and "start_button" not in col_names:
                needs_type_start_button = True
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

        try:
            await db.execute("ALTER TABLE controllers ADD COLUMN bluetooth_address TEXT")
        except Exception:
            pass

        if needs_type_start_button:
            try:
                await db.execute("ALTER TABLE controller_type_defaults ADD COLUMN start_button INTEGER")
                for name_pattern, *_, start_button in SEED_TYPE_DEFAULTS:
                    if start_button is not None:
                        await db.execute(
                            "UPDATE controller_type_defaults SET start_button = ? WHERE name_pattern = ?",
                            (start_button, name_pattern),
                        )
            except Exception:
                pass

        try:
            await db.execute("ALTER TABLE controllers ADD COLUMN tr2_is_start INTEGER DEFAULT 0")
        except Exception: pass

        try:
            await db.execute("ALTER TABLE controllers ADD COLUMN start_button_override INTEGER")
        except Exception: pass

        # A solo Joy-Con (L) has no "+" - fix up any already-seeded row (from
        # before this had a start_button of its own) still missing one.
        try:
            await db.execute(
                "UPDATE controller_type_defaults SET start_button = ? "
                "WHERE vendor_id = 0x057E AND product_id = 0x2006 AND start_button IS NULL",
                (_BTN_SELECT,),
            )
        except Exception:
            pass

    cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    else:
        await db.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    # SQLite UNIQUE treats NULLs as distinct, so rows with NULL vendor/product ids
    # were re-inserted on every startup. Remove accumulated duplicates first.
    await db.execute(
        "DELETE FROM controller_type_defaults WHERE id NOT IN ("
        "  SELECT MIN(id) FROM controller_type_defaults"
        "  GROUP BY name_pattern, COALESCE(vendor_id, -1), COALESCE(product_id, -1)"
        ")"
    )
    for name_pattern, img_src, snd_src, vendor_id, product_id, guid_override, start_button in SEED_TYPE_DEFAULTS:
        cursor = await db.execute(
            "SELECT 1 FROM controller_type_defaults WHERE name_pattern = ? AND vendor_id IS ? AND product_id IS ?",
            (name_pattern, vendor_id, product_id),
        )
        if await cursor.fetchone() is None:
            await db.execute(
                "INSERT INTO controller_type_defaults (name_pattern, img_src, snd_src, vendor_id, product_id, guid_override, start_button) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name_pattern, img_src, snd_src, vendor_id, product_id, guid_override, start_button),
            )

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

async def get_profiles_by_product(vendor_id: int, product_id: int) -> list[ControllerProfile]:
    """Return all controller profiles matching vendor_id + product_id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT unique_id, default_name, custom_name, img_src, snd_src, vendor_id, product_id, guid_override, bluetooth_address, tr2_is_start, start_button_override "
            "FROM controllers WHERE vendor_id = ? AND product_id = ? ORDER BY updated_at DESC",
            (vendor_id, product_id),
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
                bluetooth_address=r[8],
                tr2_is_start=bool(r[9]),
                start_button_override=r[10],
            )
            for r in rows
        ]
    finally:
        await db.close()


async def get_profile(unique_id: str) -> Optional[ControllerProfile]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT unique_id, default_name, custom_name, img_src, snd_src, vendor_id, product_id, guid_override, bluetooth_address, tr2_is_start, start_button_override FROM controllers WHERE unique_id = ?",
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
            bluetooth_address=row[8],
            tr2_is_start=bool(row[9]),
            start_button_override=row[10],
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
    bluetooth_address: Optional[str] = None,
    tr2_is_start: bool = False,
) -> ControllerProfile:
    """Insert or update a controller profile."""
    db = await get_db()
    try:
        existing = await db.execute("SELECT id FROM controllers WHERE unique_id = ?", (unique_id,))
        row = await existing.fetchone()

        if row:
            updates = []
            params = []
            if vendor_id is not None:
                updates.append("vendor_id = ?"); params.append(vendor_id)
            if product_id is not None:
                updates.append("product_id = ?"); params.append(product_id)
            if bluetooth_address is not None:
                updates.append("bluetooth_address = ?"); params.append(bluetooth_address)

            # Re-resolve the start-button mapping in case the type-default for this
            # controller was added/corrected after this profile was first created.
            type_default = await get_type_default(default_name, vendor_id, product_id)
            if type_default and type_default.start_button == _BTN_TR2:
                updates.append("tr2_is_start = ?"); params.append(1)
            elif type_default and type_default.start_button is not None:
                updates.append("start_button_override = ?"); params.append(type_default.start_button)

            if updates:
                params.append(unique_id)
                await db.execute(f"UPDATE controllers SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE unique_id = ?", params)
        else:
            resolved_img = img_src or "default.png"
            resolved_snd = snd_src or "default.mp3"
            resolved_guid = None
            resolved_tr2 = tr2_is_start
            resolved_start_override = None

            type_default = await get_type_default(default_name, vendor_id, product_id)
            if type_default:
                resolved_img = img_src or type_default.img_src
                resolved_snd = snd_src or type_default.snd_src
                resolved_guid = type_default.guid_override
                if type_default.start_button == _BTN_TR2:
                    resolved_tr2 = True
                elif type_default.start_button is not None:
                    resolved_start_override = type_default.start_button

            await db.execute(
                "INSERT INTO controllers (unique_id, default_name, img_src, snd_src, vendor_id, product_id, guid_override, bluetooth_address, tr2_is_start, start_button_override) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (unique_id, default_name, resolved_img, resolved_snd, vendor_id, product_id, resolved_guid, bluetooth_address, int(resolved_tr2), resolved_start_override),
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
            sets.append("custom_name = ?"); params.append(custom_name)
        if img_src is not None:
            sets.append("img_src = ?"); params.append(img_src)
        if snd_src is not None:
            sets.append("snd_src = ?"); params.append(snd_src)
        if guid_override is not ...:
            sets.append("guid_override = ?"); params.append(guid_override)

        if not sets:
            return await get_profile(unique_id)

        sets.append("updated_at = CURRENT_TIMESTAMP")
        params.append(unique_id)
        await db.execute(f"UPDATE controllers SET {', '.join(sets)} WHERE unique_id = ?", params)
        await db.commit()
    finally:
        await db.close()

    return await get_profile(unique_id)


async def delete_profile(unique_id: str) -> bool:
    """Delete a controller profile."""
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM controllers WHERE unique_id = ?", (unique_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_all_profiles() -> list[ControllerProfile]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT unique_id, default_name, custom_name, img_src, snd_src, vendor_id, product_id, guid_override, bluetooth_address, tr2_is_start, start_button_override FROM controllers ORDER BY id"
        )
        rows = await cursor.fetchall()
        profiles = [
            ControllerProfile(
                unique_id=r[0],
                default_name=r[1],
                custom_name=r[2],
                img_src=r[3] or "default.png",
                snd_src=r[4] or "default.mp3",
                vendor_id=r[5],
                product_id=r[6],
                guid_override=r[7],
                bluetooth_address=r[8],
                tr2_is_start=bool(r[9]),
                start_button_override=r[10],
            )
            for r in rows
        ]

        td_cursor = await db.execute("SELECT vendor_id, product_id, name_pattern, start_button FROM controller_type_defaults")
        type_defaults = await td_cursor.fetchall()
        vid_pid_map = {(r[0], r[1]): r[3] for r in type_defaults if r[0] is not None}
        name_map = [(r[2].lower(), r[3]) for r in type_defaults if r[0] is None]

        for p in profiles:
            if p.vendor_id is not None and p.product_id is not None:
                p.start_button = vid_pid_map.get((p.vendor_id, p.product_id))
            else:
                for name_pattern, start_btn in name_map:
                    if name_pattern in p.default_name.lower():
                        p.start_button = start_btn; break
        return profiles
    finally:
        await db.close()


async def update_type_default_start_button(
    vendor_id: Optional[int],
    product_id: Optional[int],
    default_name: str,
    start_button: Optional[int],
) -> bool:
    db = await get_db()
    try:
        if vendor_id is not None and product_id is not None:
            await db.execute("UPDATE controller_type_defaults SET start_button = ? WHERE vendor_id = ? AND product_id = ?", (start_button, vendor_id, product_id))
        else:
            cursor = await db.execute("SELECT name_pattern FROM controller_type_defaults WHERE vendor_id IS NULL")
            name_rows = await cursor.fetchall()
            for row in name_rows:
                if row[0].lower() in default_name.lower():
                    await db.execute("UPDATE controller_type_defaults SET start_button = ? WHERE name_pattern = ? AND vendor_id IS NULL", (start_button, row[0]))
                    break
        await db.commit(); return True
    except Exception: return False
    finally: await db.close()


async def get_type_default(device_name: str, vendor_id: Optional[int] = None, product_id: Optional[int] = None) -> Optional[ControllerTypeDefault]:
    db = await get_db()
    try:
        if vendor_id is not None and product_id is not None:
            cursor = await db.execute("SELECT name_pattern, img_src, snd_src, vendor_id, product_id, guid_override, start_button FROM controller_type_defaults WHERE vendor_id = ? AND product_id = ?", (vendor_id, product_id))
            row = await cursor.fetchone()
            if row: return ControllerTypeDefault(name_pattern=row[0], img_src=row[1] or "default.png", snd_src=row[2] or "default.mp3", vendor_id=row[3], product_id=row[4], guid_override=row[5], start_button=row[6])

        cursor = await db.execute("SELECT name_pattern, img_src, snd_src, vendor_id, product_id, guid_override, start_button FROM controller_type_defaults WHERE vendor_id IS NULL")
        rows = await cursor.fetchall()
        for row in rows:
            if row[0].lower() in device_name.lower():
                return ControllerTypeDefault(name_pattern=row[0], img_src=row[1] or "default.png", snd_src=row[2] or "default.mp3", vendor_id=row[3], product_id=row[4], guid_override=row[5], start_button=row[6])
        return None
    finally: await db.close()


async def get_all_emulator_configs() -> list[EmulatorConfig]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, emulator_name, config_path, enabled FROM emulator_configs ORDER BY id")
        rows = await cursor.fetchall()
        return [EmulatorConfig(id=r[0], emulator_name=r[1], config_path=r[2], enabled=bool(r[3])) for r in rows]
    finally: await db.close()


async def update_emulator_config(emulator_name: str, config_path: Optional[str] = None, enabled: Optional[bool] = None) -> Optional[EmulatorConfig]:
    db = await get_db()
    try:
        sets = []; params = []
        if config_path is not None: sets.append("config_path = ?"); params.append(config_path)
        if enabled is not None: sets.append("enabled = ?"); params.append(int(enabled))
        if not sets: return None
        params.append(emulator_name)
        await db.execute(f"UPDATE emulator_configs SET {', '.join(sets)} WHERE emulator_name = ?", params)
        await db.commit()
        cursor = await db.execute("SELECT id, emulator_name, config_path, enabled FROM emulator_configs WHERE emulator_name = ?", (emulator_name,))
        row = await cursor.fetchone()
        if not row: return None
        return EmulatorConfig(id=row[0], emulator_name=row[1], config_path=row[2], enabled=bool(row[3]))
    finally: await db.close()
