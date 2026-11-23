// Import order is load-bearing.
//
// Fonts first (they are @font-face only). Then antd's reset, which is our ONLY
// reset — Tailwind's preflight is deliberately not imported, see
// assets/main.css. Our stylesheet last so its base layer wins over the reset.
import '@fontsource-variable/bricolage-grotesque/opsz.css'
import '@fontsource-variable/manrope/wght.css'
import '@fontsource/space-mono/400.css'
import '@fontsource/space-mono/700.css'
import 'ant-design-vue/dist/reset.css'
import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
