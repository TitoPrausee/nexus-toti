"""
Minecraft 1.21 NBT Structure Generator Template
Pure Python, no dependencies (struct + os only)

Usage:
  1. Copy this template to your mod project
  2. Define your block aliases
  3. Write fill/set_block calls to build structures
  4. Run: python3 generate_structures.py
  5. NBT files appear in src/main/resources/data/yourmod/structures/
"""

import struct, os

# ---- CONFIG ----
MOD_ID = "yourmod"
BASE = os.path.expanduser("~/your-mod")
STRUCT_DIR = os.path.join(BASE, "src/main/resources/data", MOD_ID, "structures")

# ---- BLOCK ALIASES (change to your mod's blocks) ----
EXAMPLE_BRICK = f"{MOD_ID}:example_brick"
EXAMPLE_STAIRS = f"{MOD_ID}:example_stairs"
EXAMPLE_SLAB = f"{MOD_ID}:example_slab"
EXAMPLE_LAMP = f"{MOD_ID}:example_lamp"
EXAMPLE_BANNER = f"{MOD_ID}:example_banner"
JIGSAW = "minecraft:jigsaw"
AIR = "minecraft:air"

OAK_PLANKS = "minecraft:oak_planks"
GLASS_PANE = "minecraft:glass_pane"
IRON_BARS = "minecraft:iron_bars"
STONE_BRICKS = "minecraft:stone_bricks"


def make_nbt(filename, size_x, size_y, size_z, blocks):
    """
    Generate a Minecraft 1.21 structure NBT file.

    Args:
        filename: output name (without .nbt)
        size_x, size_y, size_z: dimensions of the structure
        blocks: list of (x, y, z, block_id) tuples
    """
    # Build palette
    palette = []
    palette_map = {}
    for _, _, _, bid in blocks:
        if bid not in palette_map:
            palette_map[bid] = len(palette)
            palette.append(bid)

    if not palette:
        palette.append(AIR)
        palette_map[AIR] = 0

    buf = bytearray()

    def wb(b):
        buf.append(b & 0xFF)

    def ws(s):
        buf.extend(struct.pack(">h", s))

    def wi(i):
        buf.extend(struct.pack(">i", i))

    def wstr(s):
        data = s.encode("utf-8")
        ws(len(data))
        buf.extend(data)

    # Root TAG_Compound("")
    wb(10)
    wstr("")

    # size: TAG_List of 3 TAG_Int
    wb(9)
    wstr("size")
    wb(3)
    wi(3)
    wi(size_x)
    wi(size_y)
    wi(size_z)

    # entities: empty TAG_List
    wb(9)
    wstr("entities")
    wb(10)
    wi(0)

    # palette: TAG_List of TAG_Compound
    wb(9)
    wstr("palette")
    wb(10)
    wi(len(palette))
    for bid in palette:
        wb(10)
        wstr("")
        wb(8)
        wstr("Name")
        wstr(bid)
        wb(0)  # end blockstate

    # blocks: TAG_List of TAG_Compound
    wb(9)
    wstr("blocks")
    wb(10)
    wi(len(blocks))
    for x, y, z, bid in blocks:
        wb(10)
        wstr("")
        # pos: TAG_List of 3 TAG_Int
        wb(9)
        wstr("pos")
        wb(3)
        wi(3)
        wi(x)
        wi(y)
        wi(z)
        # state: TAG_Int palette index
        wb(3)
        wstr("state")
        wi(palette_map[bid])
        wb(0)  # end block entry

    wb(0)  # end root compound

    os.makedirs(STRUCT_DIR, exist_ok=True)
    filepath = os.path.join(STRUCT_DIR, f"{filename}.nbt")
    with open(filepath, "wb") as f:
        f.write(buf)
    print(f"  ✅ {filename}.nbt ({len(buf)} bytes, {len(blocks)} blocks)")


def fill(blocks, x1, x2, y1, y2, z1, z2, bid):
    """Fill a rectangular volume with the same block."""
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            for z in range(z1, z2 + 1):
                blocks.append((x, y, z, bid))


def set_block(blocks, x, y, z, bid):
    """Place a single block."""
    blocks.append((x, y, z, bid))


# ============================================================
# EXAMPLE: Generate a simple building
# ============================================================
if __name__ == "__main__":
    print(f"Generating structures in {STRUCT_DIR}...\n")

    # -- Example building: 5x4x5 town hall --
    blocks = []
    sx, sy, sz = 5, 4, 5

    # Foundation
    fill(blocks, 0, sx - 1, 0, 0, 0, sz - 1, EXAMPLE_BRICK)

    # Walls (y=1 to y=2)
    for y in range(1, 3):
        fill(blocks, 0, sx - 1, y, y, 0, 0, EXAMPLE_BRICK)  # front
        fill(blocks, 0, sx - 1, y, y, sz - 1, sz - 1, EXAMPLE_BRICK)  # back
        fill(blocks, 0, 0, y, y, 0, sz - 1, EXAMPLE_BRICK)  # left
        fill(blocks, sx - 1, sx - 1, y, y, 0, sz - 1, EXAMPLE_BRICK)  # right

    # Door
    fill(blocks, 2, 2, 1, 2, 0, 0, AIR)

    # Roof
    fill(blocks, 0, sx - 1, sy - 1, sy - 1, 0, sz - 1, EXAMPLE_SLAB)

    # Banner on roof
    set_block(blocks, 2, sy - 1, 2, EXAMPLE_BANNER)

    # Jigsaw block for connecting to other pieces
    set_block(blocks, 2, 0, 2, JIGSAW)

    make_nbt("example_town_hall", sx, sy, sz, blocks)
    print("\nDone!")
