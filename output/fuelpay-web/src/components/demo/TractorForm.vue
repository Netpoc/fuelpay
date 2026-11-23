<script setup lang="ts">
/**
 * A tractor to monitor: the machine and its tank, the yard it sleeps in, and
 * the field it works.
 *
 * The field is drawn live as an oriented rectangle so the prospect can see the
 * shape the simulator will plough. The same geometry runs server-side, so
 * what is drawn here is exactly where the field passes will fall.
 */
import { computed, reactive, ref } from 'vue'
import { Alert, Button, Input, InputNumber, Select, Slider } from 'ant-design-vue'

import PointPicker, { type PickerPoint } from './PointPicker.vue'
import { fieldPolygon, haversineM, hectares } from '@/lib/field'
import type { FieldOperation, TractorInput } from '@/api/types'
import { BRAND } from '@/theme/tokens'

withDefaults(defineProps<{ submitting?: boolean; error?: string | null }>(), {
  submitting: false,
  error: null,
})
const emit = defineEmits<{ submit: [TractorInput]; cancel: [] }>()

const OPERATIONS: { value: FieldOperation; label: string }[] = [
  { value: 'PLOUGHING', label: 'Ploughing' },
  { value: 'HARROWING', label: 'Harrowing' },
  { value: 'SOWING', label: 'Sowing' },
  { value: 'SPRAYING', label: 'Spraying' },
  { value: 'TRANSPORT', label: 'Haulage' },
]
const HOURS = Array.from({ length: 24 }, (_, h) => ({ value: h, label: `${String(h).padStart(2, '0')}:00` }))

const form = reactive({
  name: '',
  make_model: '',
  engine_kw: 90,
  tank_capacity_l: 250,
  operation: 'PLOUGHING' as FieldOperation,
  start: 6,
  end: 18,
  yard: null as { lat: number; lon: number } | null,
  field: null as { lat: number; lon: number } | null,
  width: 400,
  length: 600,
  heading: 0,
})

/** Which point the next map click places. Advances yard -> field on its own. */
const placing = ref<'yard' | 'field'>('yard')

function pick(lat: number, lon: number) {
  const point = { lat: Number(lat.toFixed(6)), lon: Number(lon.toFixed(6)) }
  if (placing.value === 'yard') {
    form.yard = point
    if (!form.field) placing.value = 'field'
  } else {
    form.field = point
  }
}

const polygon = computed(() =>
  form.field
    ? fieldPolygon({
        latitude: form.field.lat,
        longitude: form.field.lon,
        width_m: form.width,
        length_m: form.length,
        heading_deg: form.heading,
      })
    : null,
)

const points = computed<PickerPoint[]>(() => [
  ...(form.yard ? [{ id: 'yard', ...form.yard, label: 'Yard', color: BRAND.mist }] : []),
  ...(form.field ? [{ id: 'field', ...form.field, label: 'Field', color: BRAND.saffron }] : []),
])

const distanceKm = computed(() =>
  form.yard && form.field
    ? haversineM(form.yard.lat, form.yard.lon, form.field.lat, form.field.lon) / 1000
    : null,
)

const problems = computed(() => {
  const out: string[] = []
  if (form.name.trim().length < 2) out.push('Give the tractor a name.')
  if (!form.yard) out.push('Place the yard on the map.')
  if (!form.field) out.push('Place the field on the map.')
  if (distanceKm.value !== null && distanceKm.value > 25)
    out.push('The field must be within 25 km of the yard.')
  if (form.end <= form.start) out.push('Working hours must end after they start.')
  return out
})

function submit() {
  if (problems.value.length || !form.yard || !form.field) return
  emit('submit', {
    name: form.name.trim(),
    make_model: form.make_model.trim() || undefined,
    engine_kw: form.engine_kw,
    tank_capacity_l: form.tank_capacity_l,
    yard: { latitude: form.yard.lat, longitude: form.yard.lon },
    field: {
      latitude: form.field.lat,
      longitude: form.field.lon,
      width_m: form.width,
      length_m: form.length,
      heading_deg: form.heading,
    },
    primary_operation: form.operation,
    working_hours_start: form.start,
    working_hours_end: form.end,
  })
}
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <div class="grid2">
      <label class="field">
        <span class="label">Tractor name</span>
        <Input v-model:value="form.name" placeholder="e.g. Tractor 3 — North farm" size="large" />
      </label>
      <label class="field">
        <span class="label">Make and model <span class="opt">optional</span></span>
        <Input v-model:value="form.make_model" placeholder="e.g. John Deere 6120M" size="large" />
      </label>
    </div>

    <div class="grid3">
      <label class="field">
        <span class="label">Engine power</span>
        <InputNumber v-model:value="form.engine_kw" :min="50" :max="300" :step="5" addon-after="kW" style="width: 100%" />
      </label>
      <label class="field">
        <span class="label">Fuel tank</span>
        <InputNumber v-model:value="form.tank_capacity_l" :min="150" :max="600" :step="10" addon-after="L" style="width: 100%" />
      </label>
      <label class="field">
        <span class="label">Main operation</span>
        <Select v-model:value="form.operation" :options="OPERATIONS" />
      </label>
    </div>

    <fieldset class="field">
      <legend class="label">Yard and field</legend>
      <div class="seg" role="radiogroup" aria-label="Which point the next map click places">
        <button
          v-for="which in ['yard', 'field'] as const"
          :key="which"
          type="button"
          role="radio"
          :aria-checked="placing === which"
          class="seg__btn"
          :class="{ 'seg__btn--on': placing === which }"
          @click="placing = which"
        >
          <span class="dot" :data-which="which" />
          {{ which === 'yard' ? 'Place yard' : 'Place field' }}
          <span v-if="(which === 'yard' ? form.yard : form.field)" class="set">✓</span>
        </button>
      </div>
      <PointPicker :points="points" :polygon="polygon" :place-zoom="14" @pick="pick" />
      <p class="note">
        <template v-if="distanceKm !== null">{{ distanceKm.toFixed(1) }} km from yard to field · </template>
        Field {{ hectares({ width_m: form.width, length_m: form.length }).toFixed(1) }} ha
      </p>
    </fieldset>

    <div class="grid3">
      <label class="field">
        <span class="label">Field width · {{ form.width }} m</span>
        <Slider v-model:value="form.width" :min="150" :max="1500" :step="10" />
      </label>
      <label class="field">
        <span class="label">Field length · {{ form.length }} m</span>
        <Slider v-model:value="form.length" :min="150" :max="1500" :step="10" />
      </label>
      <label class="field">
        <span class="label">Rows run at · {{ form.heading }}°</span>
        <Slider v-model:value="form.heading" :min="0" :max="179" :step="1" />
      </label>
    </div>

    <div class="grid2">
      <label class="field">
        <span class="label">Shift starts</span>
        <Select v-model:value="form.start" :options="HOURS" />
      </label>
      <label class="field">
        <span class="label">Shift ends</span>
        <Select v-model:value="form.end" :options="HOURS.slice(1).concat({ value: 24, label: '24:00' })" />
      </label>
    </div>
    <p class="note">
      Use outside these hours, or away from the field, is reported as misuse.
    </p>

    <Alert v-if="error" type="error" :message="error" show-icon />
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
        >Create tractor</Button
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
.grid2, .grid3 { display: grid; gap: 12px; grid-template-columns: 1fr }
@media (min-width: 640px) {
  .grid2 { grid-template-columns: 1fr 1fr }
  .grid3 { grid-template-columns: repeat(3, 1fr) }
}
.seg { display: flex; gap: 6px; margin-bottom: 8px }
.seg__btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; min-height: 36px;
  font: inherit; font-size: 13px; color: var(--ink-muted);
  background: var(--surface-raised); border: 1px solid var(--hairline);
  border-radius: var(--radius-control); cursor: pointer;
}
.seg__btn--on { color: var(--ink); border-color: var(--accent); font-weight: 600 }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--np-mist) }
.dot[data-which='field'] { background: var(--np-saffron) }
.set { color: var(--status-ok-text) }
.note { margin: 0; font-size: 12px; color: var(--ink-muted) }
.problems { margin: 0; padding-left: 18px; font-size: 12px; color: var(--status-watch-text) }
.actions { display: flex; justify-content: space-between; gap: 12px }
</style>
