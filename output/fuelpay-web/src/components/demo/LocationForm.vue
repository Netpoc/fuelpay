<script setup lang="ts">
/**
 * A location to monitor: where it is, its generators and their day tanks, and
 * any bulk storage.
 *
 * The bounds are FuelPay's market rules, not form decoration: day tanks from
 * 1000 L, bulk from 5000 L, generators on the standard 25–100 kVA ratings. The
 * server enforces the same rules; mirroring them here just means the prospect
 * finds out before pressing submit.
 */
import { computed, reactive, watch } from 'vue'
import { Alert, Button, Input, InputNumber, Select } from 'ant-design-vue'

import PointPicker, { type PickerPoint } from './PointPicker.vue'
import type { LocationInput, SiteProfile } from '@/api/types'

const props = withDefaults(
  defineProps<{ maxGenerators?: number; submitting?: boolean; error?: string | null }>(),
  { maxGenerators: 3, submitting: false, error: null },
)
const emit = defineEmits<{ submit: [LocationInput]; cancel: [] }>()

const KVA_OPTIONS = [25, 30, 40, 50, 60, 75, 100].map((k) => ({ value: k, label: `${k} kVA` }))
const PROFILES: { value: SiteProfile; label: string }[] = [
  { value: 'BANK_BRANCH', label: 'Bank branch' },
  { value: 'TELECOM_TOWER', label: 'Telecom tower' },
  { value: 'OFFICE', label: 'Office' },
  { value: 'RESIDENTIAL', label: 'Residential estate' },
]
/** Starting sizes per profile, matching app/simulation/profiles.py defaults. */
const DEFAULTS: Record<SiteProfile, { kva: number; day: number; bulk: number | null }> = {
  BANK_BRANCH: { kva: 75, day: 1500, bulk: 10_000 },
  TELECOM_TOWER: { kva: 50, day: 1000, bulk: 5_000 },
  OFFICE: { kva: 60, day: 1000, bulk: 5_000 },
  RESIDENTIAL: { kva: 30, day: 1000, bulk: null },
}

const form = reactive({
  name: '',
  profile: 'BANK_BRANCH' as SiteProfile,
  address: '',
  latitude: undefined as number | undefined,
  longitude: undefined as number | undefined,
  generators: [{ name: 'GEN-1', kva_rating: 75, day_tank_capacity_l: 1500 }],
  bulk: [{ capacity_l: 10_000 }] as { capacity_l: number }[],
})

// A profile change re-seeds sizes only while the user has not touched them.
let pristine = true
let seeding = false
watch(
  () => form.profile,
  (profile) => {
    if (!pristine) return
    const d = DEFAULTS[profile]
    seeding = true
    form.generators = [{ name: 'GEN-1', kva_rating: d.kva, day_tank_capacity_l: d.day }]
    form.bulk = d.bulk ? [{ capacity_l: d.bulk }] : []
    seeding = false
  },
)
// Synchronous, so it sees the re-seed above with `seeding` still set and only
// a real user edit flips `pristine`.
watch(
  () => [form.generators, form.bulk],
  () => {
    if (!seeding) pristine = false
  },
  { deep: true, flush: 'sync' },
)

function addGenerator() {
  if (form.generators.length >= props.maxGenerators) return
  const d = DEFAULTS[form.profile]
  form.generators.push({
    name: `GEN-${form.generators.length + 1}`,
    kva_rating: d.kva,
    day_tank_capacity_l: d.day,
  })
}

const points = computed<PickerPoint[]>(() =>
  form.latitude !== undefined && form.longitude !== undefined
    ? [{ id: 'site', lat: form.latitude, lon: form.longitude, label: form.name || 'Location', color: '#f2a93b' }]
    : [],
)

function pick(lat: number, lon: number) {
  form.latitude = Number(lat.toFixed(6))
  form.longitude = Number(lon.toFixed(6))
}

const names = computed(() => form.generators.map((g) => g.name.trim().toLowerCase()))
const problems = computed(() => {
  const out: string[] = []
  if (form.name.trim().length < 2) out.push('Give the location a name.')
  if (form.latitude === undefined || form.longitude === undefined) out.push('Place the location on the map.')
  if (form.generators.some((g) => !g.name.trim())) out.push('Every generator needs a name.')
  if (new Set(names.value).size !== names.value.length) out.push('Generator names must differ.')
  if (form.generators.some((g) => (g.day_tank_capacity_l ?? 0) < 1000))
    out.push('Day tanks start at 1000 L.')
  if (form.bulk.some((b) => (b.capacity_l ?? 0) < 5000)) out.push('Bulk tanks start at 5000 L.')
  return out
})

function submit() {
  if (problems.value.length) return
  emit('submit', {
    name: form.name.trim(),
    profile: form.profile,
    latitude: form.latitude!,
    longitude: form.longitude!,
    address: form.address.trim() || undefined,
    generators: form.generators.map((g) => ({ ...g, name: g.name.trim() })),
    bulk_tanks: form.bulk,
  })
}
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <div class="grid2">
      <label class="field">
        <span class="label">Location name</span>
        <Input v-model:value="form.name" placeholder="e.g. Lekki Phase 1 Branch" size="large" />
      </label>
      <label class="field">
        <span class="label">Type of site</span>
        <Select v-model:value="form.profile" :options="PROFILES" size="large" />
      </label>
    </div>

    <label class="field">
      <span class="label">Address <span class="opt">optional</span></span>
      <Input v-model:value="form.address" placeholder="Street, city" />
    </label>

    <fieldset class="field">
      <legend class="label">Where is it? <span class="opt">click the map</span></legend>
      <PointPicker :points="points" :place-zoom="15" @pick="pick" />
      <div class="grid2 mt">
        <label class="inline">
          <span>Latitude</span>
          <InputNumber v-model:value="form.latitude" :min="-90" :max="90" :step="0.0001" style="width: 100%" />
        </label>
        <label class="inline">
          <span>Longitude</span>
          <InputNumber v-model:value="form.longitude" :min="-180" :max="180" :step="0.0001" style="width: 100%" />
        </label>
      </div>
    </fieldset>

    <fieldset class="field">
      <legend class="label">
        Generators <span class="opt">{{ form.generators.length }} of {{ maxGenerators }}</span>
      </legend>
      <div v-for="(gen, i) in form.generators" :key="i" class="row">
        <Input v-model:value="gen.name" :aria-label="`Generator ${i + 1} name`" class="row__name" />
        <Select
          v-model:value="gen.kva_rating"
          :options="KVA_OPTIONS"
          :aria-label="`Generator ${i + 1} rating`"
          class="row__kva"
        />
        <InputNumber
          v-model:value="gen.day_tank_capacity_l"
          :min="1000"
          :max="20000"
          :step="100"
          addon-after="L day tank"
          :aria-label="`Generator ${i + 1} day tank litres`"
          class="row__tank"
        />
        <Button
          v-if="form.generators.length > 1"
          type="text"
          :aria-label="`Remove generator ${i + 1}`"
          @click="form.generators.splice(i, 1)"
          >✕</Button
        >
      </div>
      <Button
        v-if="form.generators.length < maxGenerators"
        type="dashed"
        block
        @click="addGenerator"
        >+ Add generator</Button
      >
    </fieldset>

    <fieldset class="field">
      <legend class="label">Bulk storage <span class="opt">external tanks, 5000 L+</span></legend>
      <div v-for="(tank, i) in form.bulk" :key="i" class="row">
        <InputNumber
          v-model:value="tank.capacity_l"
          :min="5000"
          :max="100000"
          :step="500"
          addon-before="Bulk"
          addon-after="L"
          :aria-label="`Bulk tank ${i + 1} litres`"
          class="row__bulk"
        />
        <Button type="text" :aria-label="`Remove bulk tank ${i + 1}`" @click="form.bulk.splice(i, 1)"
          >✕</Button
        >
      </div>
      <Button v-if="form.bulk.length < 4" type="dashed" block @click="form.bulk.push({ capacity_l: 5000 })"
        >+ Add bulk tank</Button
      >
    </fieldset>

    <p class="note">
      Every tank is created with a calibrated fuel sensor — FuelPay only monitors tanks it can sense.
    </p>

    <Alert v-if="error" type="error" :message="error" show-icon class="mb" />
    <ul v-if="problems.length && form.name" class="problems">
      <li v-for="p in problems" :key="p">{{ p }}</li>
    </ul>

    <div class="actions">
      <Button size="large" @click="emit('cancel')">Back</Button>
      <Button
        type="primary"
        size="large"
        html-type="submit"
        :loading="submitting"
        :disabled="problems.length > 0"
        >Create location</Button
      >
    </div>
  </form>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 18px }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0 }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0 }
.label { font-size: 13px; font-weight: 600; padding: 0 }
.opt { font-weight: 400; color: var(--ink-muted); margin-left: 4px }
.grid2 { display: grid; gap: 12px; grid-template-columns: 1fr }
@media (min-width: 640px) { .grid2 { grid-template-columns: 1fr 1fr } }
.mt { margin-top: 8px }
.inline { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-muted) }
.row { display: grid; gap: 8px; grid-template-columns: 1fr auto; align-items: center; margin-bottom: 8px }
@media (min-width: 640px) {
  .row { grid-template-columns: minmax(0, 1fr) 120px 200px auto }
  .row:has(.row__bulk) { grid-template-columns: minmax(0, 260px) auto }
}
.row__name { grid-column: 1 / -1 }
@media (min-width: 640px) { .row__name { grid-column: auto } }
.row__tank, .row__bulk { width: 100% }
.note { margin: 0; font-size: 12px; color: var(--ink-muted) }
.problems { margin: 0; padding-left: 18px; font-size: 12px; color: var(--status-watch-text) }
.mb { margin-bottom: 4px }
.actions { display: flex; justify-content: space-between; gap: 12px }
</style>
