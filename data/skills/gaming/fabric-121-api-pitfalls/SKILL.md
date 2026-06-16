---
name: fabric-121-api-pitfalls
description: Common Fabric 1.21 Yarn mapping & API gotchas — screen handlers, block entities, slot classes, NBT, fuel detection, and property delegates. Use when developing or fixing Fabric mods targeting 1.21.
---

# Fabric 1.21 API Pitfalls & Gotchas

This skill documents differences in Fabric 1.21 (Yarn mappings b.9) that commonly trip up mod developers.

## Block Entity NBT

In 1.21, `readNbt` and `writeNbt` require a `RegistryWrapper.WrapperLookup` parameter:

```java
@Override
protected void readNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registryLookup) {
    super.readNbt(nbt, registryLookup);
    // custom fields: use nbt.getInt("key") — NO default value overload
    myField = nbt.contains("MyField") ? nbt.getInt("MyField") : 0;
}

@Override
protected void writeNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registryLookup) {
    super.writeNbt(nbt, registryLookup);
    nbt.putInt("MyField", myField);
}
```

**Key difference**: `nbt.getInt(key)` has only one parameter (no default-value overloads). Check with `nbt.contains(key)` first.

Same applies to `getFloat`, `getString`, etc.

## Screen Handler Slots

### FurnaceFuelSlot
Constructor changed — requires `AbstractFurnaceScreenHandler` as first arg:

```java
// 1.21: (AbstractFurnaceScreenHandler, Inventory, slotIndex, x, y)
this.addSlot(new FurnaceFuelSlot(this, inventory, 1, 56, 53));
```

### FurnaceOutputSlot
Constructor requires `PlayerEntity` as first arg:

```java
// 1.21: (PlayerEntity, Inventory, slotIndex, x, y)
this.addSlot(new FurnaceOutputSlot(playerInventory.player, inventory, 2, 116, 35));
```

### Simple slots (no special behavior)
Use plain `Slot` if you don't need fuel/output behavior:

```java
this.addSlot(new Slot(inventory, slotIndex, x, y));
```

## Fuel Detection

**DO NOT use** `stack.getBurnTime()` — it doesn't exist on ItemStack in 1.21.

Use the static method on AbstractFurnaceBlockEntity:

```java
boolean isFuel = AbstractFurnaceBlockEntity.canUseAsFuel(stack);
```

## Player Detection in ServerWorld

`ServerWorld.getPlayers()` returns `List<ServerPlayerEntity>` (not `List<PlayerEntity>`) in 1.21:

```java
import net.minecraft.server.network.ServerPlayerEntity;

List<ServerPlayerEntity> players = sw.getPlayers(p -> 
    !p.isSpectator() && p.squaredDistanceTo(...) < radius * radius
);
```

## Property Delegate for Custom GUI Data

For syncing custom data (player count, multipliers, etc.) from server to client:

1. Define property IDs as int constants (0..N-1)
2. Create a `PropertyDelegate` anonymous class with `get()`, `set()`, `size()`
3. `addProperties(propertyDelegate)` in the ScreenHandler constructor
4. Read values in ScreenHandler getters through `propertyDelegate.get(PROP_ID)`
5. Read values in Screen `drawForeground()` through handler getters

The properties array is synced automatically by Minecraft's container system — no custom packets needed for simple int data.

## Experience Orb Spawning

`ExperienceOrbEntity.spawn()` requires a `Vec3d` position in 1.21 — **not** `BlockPos`:

```java
// WRONG — compile error
ExperienceOrbEntity.spawn(sw, be.pos.up(), savedXp);

// CORRECT — convert BlockPos to Vec3d
ExperienceOrbEntity.spawn(sw, be.pos.up().toCenterPos(), savedXp);
// or: Vec3d.ofCenter(be.pos.up())
```

Signature: `ExperienceOrbEntity.spawn(ServerWorld world, Vec3d pos, int amount)`

## HopperBlockEntity.transfer

The 5-arg `HopperBlockEntity.transfer(Inventory, Inventory, ItemStack, Direction)` and 6-arg `transfer(Inventory, Inventory, ItemStack, int, Direction)` overloads do **not exist** in Fabric 1.21 Yarn mappings. If you need programmatic item insertion into an adjacent inventory, use a custom helper:

```java
private static ItemStack tryInsert(Inventory inv, ItemStack stack, Direction side) {
    if (stack.isEmpty()) return stack;
    for (int i = 0; i < inv.size(); i++) {
        if (!inv.isValid(i, stack)) continue;
        ItemStack slot = inv.getStack(i);
        if (slot.isEmpty()) {
            inv.setStack(i, stack.copy());
            inv.markDirty();
            return ItemStack.EMPTY;
        }
        if (ItemStack.areItemsAndComponentsEqual(slot, stack) && slot.getCount() < slot.getMaxCount()) {
            int space = slot.getMaxCount() - slot.getCount();
            int toAdd = Math.min(space, stack.getCount());
            slot.increment(toAdd);
            stack.decrement(toAdd);
            inv.markDirty();
            if (stack.isEmpty()) return ItemStack.EMPTY;
        }
    }
    return stack;
}
```

## Anonymous Inventory Classes

If you implement `Inventory` anonymously for transfer helpers, you **must** override `clear()`:

```java
new Inventory() {
    // ... all required methods ...
    @Override public void clear() {}
};
```

Without `clear()`, you get: `is not abstract and does not override abstract method clear() in Clearable`

This is because `Inventory` extends `Clearable` in 1.21 which has `void clear()`.

## GUI Textures

For custom GUI textures:
- Standard container size: 176×166 pixels
- Arrow progress overlay: placed at (176, 14) in the texture sheet, 24×17 pixels
- Flame/fuel gauge overlay: placed at (176, 0) in the texture sheet, 14×14 pixels
- If Pillow is unavailable, generate PNGs with raw Python struct+zlib (see minecraft-mod-project-workflow for texture generation)

## Music Disc Registration

`net.minecraft.item.MusicDiscItem` **does not exist** in Minecraft 1.21 Fabric Yarn mappings. It was removed in the 1.21 data component refactor.

In 1.21, music discs are registered as regular `Item` instances with a `jukebox_playable` component:

```java
import net.minecraft.component.DataComponentTypes;
import net.minecraft.component.type.JukeboxPlayableComponent;
import net.minecraft.item.Item;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.registry.RegistryKey;
import net.minecraft.registry.RegistryKeys;
import net.minecraft.registry.RegistryPair;
import net.minecraft.util.Identifier;
import net.minecraft.util.Rarity;

public static final Item MY_DISC = Registry.register(
    Registries.ITEM,
    Identifier.of(MOD_ID, "my_disc"),
    new Item(new Item.Settings()
        .maxCount(1)
        .rarity(Rarity.RARE)
        .component(DataComponentTypes.JUKEBOX_PLAYABLE,
            new JukeboxPlayableComponent(
                new RegistryPair<>(RegistryKey.of(RegistryKeys.JUKEBOX_SONG, Identifier.of(MOD_ID, "my_disc"))),
                true // show_tooltip
            ))
    )
);
```

Then register a jukebox_song JSON under `data/<modid>/jukebox_song/<name>.json`:

```json
{
  "comparator_output": 1,
  "description": {
    "translate": "item.<modid>.my_disc.desc"
  },
  "length_in_seconds": 8.0,
  "sound_event": {
    "sound_id": "<modid>:my_disc"
  }
}
```

The comparator output value (1-15) controls the redstone signal strength when the disc is in a jukebox.

**Key difference from pre-1.21**: Instead of a dedicated `MusicDiscItem` class with comparator_output as a constructor parameter, 1.21 uses a `JukeboxPlayableComponent` with a `RegistryKey<JukeboxSong>` that points to a data file containing the comparator output and sound event.

For the `.ogg` file and `sounds.json` entry, the setup is the same as any other streaming sound — add the file to `sounds/<name>.ogg` and register it in `sounds.json` with `"stream": true`.

## BrewingRecipeRegistry API (1.21)

In 1.21 Fabric (Yarn), `BrewingRecipeRegistry` methods are **instance methods**, not static:

```java
// WRONG - compile errors
BrewingRecipeRegistry.isValidIngredient(stack);   // non-static method
BrewingRecipeRegistry.craft(ingredient, bottle);   // non-static method

// CORRECT - get instance from world
BrewingRecipeRegistry registry = world.getBrewingRecipeRegistry();
registry.isValidIngredient(stack);
registry.craft(ingredient, bottle);  // returns ItemStack
```

**Additionally**: `net.minecraft.registry.Registries.RECIPE` does NOT exist in 1.21. Do not try to access `Registries.RECIPE`.

For screen handlers that need `BrewingRecipeRegistry` in slot validation, get the instance from the player's world:
```java
// In a Slot subclass:
private final BrewingRecipeRegistry brewingRegistry;
IngredientSlot(Inventory inventory, int index, int x, int y, BrewingRecipeRegistry brewingRegistry) {
    super(inventory, index, x, y);
    this.brewingRegistry = brewingRegistry;
}
@Override public boolean canInsert(ItemStack stack) {
    return brewingRegistry.isValidIngredient(stack);
}
```

## Potion API (1.21) — RegistryEntry vs Potion

In Minecraft 1.21, the `Potions` constants (e.g. `Potions.AWKWARD`, `Potions.WATER`, `Potions.SWIFTNESS`) are **`RegistryEntry<Potion>`** — not `Potion` instances.

### Creating potion ItemStacks

```java
import net.minecraft.component.DataComponentTypes;
import net.minecraft.component.type.PotionContentsComponent;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.potion.Potion;
import net.minecraft.potion.Potions;
import net.minecraft.registry.entry.RegistryEntry;

// CORRECT — Potions.X is already RegistryEntry<Potion>
private static ItemStack createPotion(RegistryEntry<Potion> potion) {
    ItemStack stack = new ItemStack(Items.POTION);
    stack.set(DataComponentTypes.POTION_CONTENTS, new PotionContentsComponent(potion));
    return stack;
}

// For splash/lingering:
private static ItemStack createSplashPotion(RegistryEntry<Potion> potion) {
    ItemStack stack = new ItemStack(Items.SPLASH_POTION);
    stack.set(DataComponentTypes.POTION_CONTENTS, new PotionContentsComponent(potion));
    return stack;
}
```

**Common mistake**: Writing `createPotion(Potion potion)` and then trying to wrap with `Registries.POTION.getEntry(potion)` — this fails because `Potions.AWKWARD` is already a `RegistryEntry<Potion>`, so the `Potion` parameter can't accept it.

**Solution**: Accept `RegistryEntry<Potion>` directly in helper methods. `PotionContentsComponent` constructor takes `RegistryEntry<Potion>`, so no wrapping is needed.

```java
// WRONG — incompatible types: RegistryEntry<Potion> cannot be converted to Potion
private static ItemStack createPotion(Potion potion) { ... }
createPotion(Potions.AWKWARD);  // compile error!

// CORRECT
private static ItemStack createPotion(RegistryEntry<Potion> potion) {
    stack.set(DataComponentTypes.POTION_CONTENTS, new PotionContentsComponent(potion));
}
createPotion(Potions.AWKWARD);  // works — RegistryEntry<Potion>
```

### Full imports needed

```java
import net.minecraft.component.DataComponentTypes;
import net.minecraft.component.type.PotionContentsComponent;
import net.minecraft.item.Items;
import net.minecraft.potion.Potion;
import net.minecraft.potion.Potions;
import net.minecraft.registry.entry.RegistryEntry;
```

## Enchantment API (1.21)

### EnchantmentHelper.apply() signature

`EnchantmentHelper.apply()` takes a `Consumer<Builder>` - **not** `List<EnchantmentLevelEntry>`:

```java
// WRONG
EnchantmentHelper.apply(itemStack, enchantments);  // compile error

// CORRECT - apply enchantments individually
for (EnchantmentLevelEntry entry : enchantments) {
    itemStack.addEnchantment(entry.enchantment, entry.level);
}
```

### EnchantmentLevelEntry fields

In 1.21 Yarn, `EnchantmentLevelEntry` uses **public fields**, not record accessors:

```java
// CORRECT
entry.enchantment   // RegistryEntry<Enchantment> - public field, NOT .enchantment()
entry.level         // int - public field, NOT .level()
```

### Enchantment registry streaming

`streamEntries()` on the enchantment registry returns `Stream<Reference<Enchantment>>` (a subtype of `RegistryEntry<Enchantment>`), not a raw `Stream<RegistryEntry>`:

```java
var registry = world.getRegistryManager().get(RegistryKeys.ENCHANTMENT);
registry.streamEntries()  // returns Stream<Reference<Enchantment>>
    .map(entry -> (RegistryEntry<Enchantment>) entry)  // cast if needed
```

### Enchantment compatibility

Use `EnchantmentHelper.isCompatible()` (static) instead of `Enchantment.isCompatible()`:

```java
// WRONG
entry.enchantment.value().isCompatible(other);  // may not exist

// CORRECT
EnchantmentHelper.isCompatible(enchantments, entry.enchantment);
```

## NamedScreenHandlerFactory on BlockEntities

In 1.21, a `BlockEntity` can implement `NamedScreenHandlerFactory` directly. The block's `onUse()` then opens the screen via `player.openHandledScreen(be)` where `be` is cast:

```java
// In BlockEntity class
public class MyBlockEntity extends BlockEntity implements SidedInventory, NamedScreenHandlerFactory {
    @Override
    @Nullable
    public ScreenHandler createMenu(int syncId, PlayerInventory playerInventory, PlayerEntity player) {
        return new MyScreenHandler(syncId, playerInventory, this, propertyDelegate);
    }
    @Override
    public Text getDisplayName() {
        return Text.translatable("container.modid.my_block");
    }
}

// In Block.onUse()
player.openHandledScreen((NamedScreenHandlerFactory) be);  // explicit cast works
```

## ScreenHandler Constructor References for Registry

When registering a `ScreenHandlerType` that needs a 2-arg constructor:

```java
// This works only if the ScreenHandler has a 2-arg constructor
// that chains to the full constructor
public MyScreenHandler(int syncId, PlayerInventory playerInventory) {
    this(syncId, playerInventory, new SimpleInventory(5), new ArrayPropertyDelegate(5));
}

public MyScreenHandler(int syncId, PlayerInventory playerInventory,
                       Inventory inventory, PropertyDelegate propertyDelegate) {
    super(ModScreenHandlers.MY_SCREEN, syncId);  // Pass the TYPE reference, NOT null
    // ...
}
```

The `super()` call must use the registered `ScreenHandlerType` - **not** `null` - otherwise constructor references in `ScreenHandlerType<>()` factory will fail.

## Opening Vanilla Villager Trade GUI from Custom Screen

`VillagerEntity` does **NOT** implement `NamedScreenHandlerFactory` in Fabric 1.21 Yarn mappings. Attempting `player.openHandledScreen(villager)` fails with:

```
error: incompatible types: VillagerEntity cannot be converted to NamedScreenHandlerFactory
```

**Fix:** Create an anonymous `NamedScreenHandlerFactory` that wraps the villager with a `MerchantScreenHandler`:

```java
player.openHandledScreen(new NamedScreenHandlerFactory() {
    @Override
    public Text getDisplayName() {
        return villager.getDisplayName();
    }
    @Override
    public ScreenHandler createMenu(int syncId, PlayerInventory inv, PlayerEntity player) {
        return new MerchantScreenHandler(syncId, inv, villager);
    }
});
```

This is necessary when opening the trade GUI from a custom network packet handler (e.g. from a dialogue screen's "Trade" button via C2S payload). The `MerchantScreenHandler(syncId, PlayerInventory, Merchant)` constructor accepts any `Merchant` implementation, and `VillagerEntity` implements `Merchant`.

## Jukebox Disc Support on Custom Blocks (BlockWithEntity)

Adding music disc playback to a custom block in 1.21 requires converting it to `BlockWithEntity` with a `BlockEntity` that stores the disc as NBT-persisted `ItemStack`.

### Key Steps

1. **Convert block to BlockWithEntity** — change `extends Block` to `extends BlockWithEntity`, implement `createBlockEntity()` and `getTicker()`.

2. **Create a BlockEntity** that stores `ItemStack insertedDisc`:

```java
public class MyRadioBlockEntity extends BlockEntity {
    private static final String DISC_TAG = "InsertedDisc";
    private ItemStack insertedDisc = ItemStack.EMPTY;

    public MyRadioBlockEntity(BlockPos pos, BlockState state) {
        super(ModBlockEntities.MY_RADIO, pos, state);
    }

    public boolean insertDisc(ItemStack disc) {
        if (disc.isEmpty()) return false;
        JukeboxPlayableComponent jukebox = disc.get(DataComponentTypes.JUKEBOX_PLAYABLE);
        if (jukebox == null) return false;
        if (!insertedDisc.isEmpty()) return false;
        this.insertedDisc = disc.copyWithCount(1);
        markDirty();
        return true;
    }

    public ItemStack ejectDisc() {
        ItemStack disc = this.insertedDisc;
        this.insertedDisc = ItemStack.EMPTY;
        markDirty();
        return disc;
    }

    // Write NBT
    @Override
    protected void writeNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registryLookup) {
        super.writeNbt(nbt, registryLookup);
        if (!insertedDisc.isEmpty()) {
            nbt.put(DISC_TAG, insertedDisc.encode(registryLookup));
        }
    }

    // Read NBT — ItemStack.fromNbt() returns Optional
    @Override
    protected void readNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registryLookup) {
        super.readNbt(nbt, registryLookup);
        if (nbt.contains(DISC_TAG, NbtElement.COMPOUND_TYPE)) {
            this.insertedDisc = ItemStack.fromNbt(registryLookup, nbt.getCompound(DISC_TAG))
                .orElse(ItemStack.EMPTY);
        } else {
            this.insertedDisc = ItemStack.EMPTY;
        }
    }
}
```

3. **Register the block entity** in your `ModBlockEntities` class:
```java
public static final BlockEntityType<MyRadioBlockEntity> MY_RADIO = Registry.register(
    Registries.BLOCK_ENTITY_TYPE,
    Identifier.of(MOD_ID, "my_radio"),
    BlockEntityType.Builder.create(MyRadioBlockEntity::new, ModBlocks.MY_RADIO).build()
);
```

### Resolving Disc Sound Events Dynamically

To play the disc's jukebox song sound **at runtime** from a stored ItemStack:

```java
// WARNING: Yarn mappings use key() NOT getKey()
public SoundEvent getDiscSound() {
    if (insertedDisc.isEmpty()) return null;
    JukeboxPlayableComponent jukebox = insertedDisc.get(DataComponentTypes.JUKEBOX_PLAYABLE);
    if (jukebox == null) return null;
    RegistryPair<JukeboxSong> song = jukebox.song();
    if (song != null && world != null) {
        // 🔴 Yarn 1.21: method is key() NOT getKey()
        RegistryKey<JukeboxSong> key = song.key();
        var entry = world.getRegistryManager()
                .get(RegistryKeys.JUKEBOX_SONG)
                .getEntry(key);
        if (entry.isPresent()) {
            return entry.get().value().soundEvent().value();
        }
    }
    return null;
}
```

**⚠️ Critical Yarn gotcha**: `RegistryPair` has method `key()` (not `getKey()`). Using `getKey()` causes a compilation error:
```
error: cannot find symbol
  var key = song.getKey();
                ^
  symbol:   method getKey()
  location: variable song of type RegistryPair<JukeboxSong>
```

### Sound Category for Disc Playback

Use `SoundCategory.RECORDS` for jukebox-like disc playback — this respects the user's music volume slider:

```java
world.playSound(null, pos, discSound, SoundCategory.RECORDS, volume, pitch);
```

### Scheduled Tick for Repeated Disc Playback

Schedule a tick to repeat the disc sound periodically (since discs don't loop automatically):

```java
// In scheduledTick():
if (radioBe.hasDisc() && state.get(LIT)) {
    SoundEvent discSound = radioBe.getDiscSound();
    if (discSound != null) {
        world.playSound(null, pos, discSound, SoundCategory.RECORDS, 0.8f, 1.0f);
        world.scheduleBlockTick(pos, this, DISC_PLAY_INTERVAL + random.nextInt(20));
    }
}
```

### Dropping Disc on Block Break

Override `onStateReplaced()` to scatter the disc when the block is broken:

```java
@Override
protected void onStateReplaced(BlockState state, World world, BlockPos pos, BlockState newState, boolean moved) {
    if (!state.isOf(newState.getBlock())) {
        BlockEntity be = world.getBlockEntity(pos);
        if (be instanceof MyRadioBlockEntity radioBe && radioBe.hasDisc()) {
            ItemScatterer.spawn(world, pos.getX() + 0.5, pos.getY() + 0.5, pos.getZ() + 0.5, radioBe.ejectDisc());
        }
        super.onStateReplaced(state, world, pos, newState, moved);
    }
}
```

### Comparator Output for Disc Detection

Output full signal (15) when a disc is inserted — useful for redstone automation:

```java
@Override
protected int getComparatorOutput(BlockState state, World world, BlockPos pos) {
    BlockEntity be = world.getBlockEntity(pos);
    if (be instanceof MyRadioBlockEntity radioBe && radioBe.hasDisc()) {
        return 15;
    }
    return 0;
}
```

### Detecting Jukebox-Playable Items

Check for the `JUKEBOX_PLAYABLE` data component instead of relying on `instanceof MusicDiscItem` (which was removed in 1.21):

```java
boolean isJukeboxDisc = heldItem.contains(DataComponentTypes.JUKEBOX_PLAYABLE);
```

## `randomDisplayTick` Sound Playback (Client-Side Only)

In Fabric 1.21, `randomDisplayTick()` is called **only on the client** (every tick for particles/sounds). The correct method signature for playing sounds here is the **6-argument** `world.playSound()` — no phantom boolean parameter, no `playSoundClient`:

```java
@Override
public void randomDisplayTick(BlockState state, World world, BlockPos pos, Random random) {
    // ✅ CORRECT — 6 args: (PlayerEntity, BlockPos, SoundEvent, SoundCategory, volume, pitch)
    if (random.nextInt(8) == 0) {
        world.playSound(null, pos,
                MySounds.RUMBLE.value(),
                SoundCategory.BLOCKS, 0.3f + random.nextFloat() * 0.2f,
                0.7f + random.nextFloat() * 0.3f);
    }
}
```

**Common mistakes to avoid:**

| Mistake | Error | Fix |
|---------|-------|-----|
| `world.playSoundClient(x, y, z, ...)` | `cannot find symbol: method playSoundClient` | Use `world.playSound(null, pos, ...)` — no such method exists in Fabric 1.21 |
| `world.playSound(null, pos, sound, cat, vol, pitch, false)` | `no suitable method found for playSound(...)` | The 7-arg overload with `boolean` does not exist for this signature in 1.21 — drop the last `false` |
| `world.playSound(pos.getX()+0.5, pos.getY()+0.5, ...)` | `cannot find symbol` | That overload takes `PlayerEntity`, not doubles — use the `(null, BlockPos, ...)` overload instead |

**Key insight**: The `playSound(null, BlockPos, ...)` overload with 6 parameters is the correct one for client-side ambient sounds in `randomDisplayTick`. It plays the sound at the block position for all nearby players to hear, with no extra arguments.

## Common Build Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `readNbt cannot be applied to given types` | Missing RegistryWrapper param | Add `RegistryWrapper.WrapperLookup` param |
| `cannot find symbol: class MusicDiscItem` | MusicDiscItem removed in 1.21 | Use regular Item + JukeboxPlayableComponent + RegistryPair (see above) |
| `incompatible types: RegistryKey cannot conform to RegistryPair` | JukeboxPlayableComponent constructor takes `RegistryPair<JukeboxSong>` not `RegistryKey` | Wrap key with `new RegistryPair<>(RegistryKey.of(...))` |
| `getInt(String, int)` not found | No default-value overload | Use `contains()` check first |
| `FurnaceFuelSlot constructor cannot be applied` | Missing handler param | Pass `this` as first arg |
| `getBurnTime()` not found | Wrong fuel API | Use `canUseAsFuel()` |
| `List<ServerPlayerEntity> cannot be converted to List<PlayerEntity>` | Return type mismatch | Use `List<ServerPlayerEntity>` |
| `source.isFire()` not found | Method doesn't exist in 1.21 Yarn | Use `source.getName()` and compare to string names |
| `onWorldAdded()` / `onSpawnPacket()` not overridable | Missing lifecycle hooks | Handle post-spawn in `readCustomDataFromNbt()` instead |
| `Registries.RECIPE` not found | Field doesn't exist in 1.21 | Use `world.getBrewingRecipeRegistry()` or `world.getRecipeManager()` instead |
| `BrewingRecipeRegistry.craft()` non-static | Method is instance-only in 1.21 | Get registry via `world.getBrewingRecipeRegistry()` first |
| `EnchantmentHelper.apply(ItemStack, List)` wrong signature | Takes `Consumer<Builder>` not `List` | Call `itemStack.addEnchantment()` per entry |
| `invalid constructor reference` for ScreenHandlerType | super() uses null type | Pass registered `ModScreenHandlers.XYZ` type to super() |
| `song.getKey()` cannot find symbol | Yarn 1.21 maps `RegistryPair` method as `key()` not `getKey()` | Use `song.key()` instead of `song.getKey()` |

## Entity Dynamic Upgrades

When upgrading an entity at runtime (e.g. giving 200 HP instead of 150), use this pattern:

1. **Field + NBT persistence** — Save a boolean flag like `"Upgraded"` in NBT:
   ```java
   // write
   nbt.putBoolean("Upgraded", upgraded);
   // read
   if (nbt.contains("Upgraded") && nbt.getBoolean("Upgraded")) {
       this.upgraded = true;
   }
   ```

2. **Attribute override on read** — In `readCustomDataFromNbt()`, set attribute base values after `super.readCustomDataFromNbt()`:
   ```java
   this.getAttributeInstance(EntityAttributes.GENERIC_MAX_HEALTH).setBaseValue(200.0);
   this.setHealth(200.0f); // heal to full
   ```

3. **Client-side rendering** — Pass the `upgraded` field to the renderer via `instanceof` check in `getTexture()`:
   ```java
   if (entity instanceof MyUpgradableEntity e && e.isUpgraded()) { return UPGRADED_TEXTURE; }
   ```

## Fire Damage Detection

`DamageSource.isFire()` does **not exist** in Fabric 1.21 Yarn mappings. Instead check by damage type name:

```java
@Override
public boolean damage(DamageSource source, float amount) {
    if (upgraded) {
        String name = source.getName();
        if ("inFire".equals(name) || "onFire".equals(name) || "lava".equals(name) || "hotFloor".equals(name)) {
            return false; // fire immunity
        }
    }
    return super.damage(source, amount);
}
```
