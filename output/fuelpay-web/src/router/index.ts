import { createRouter, createWebHistory } from 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    /** Renders without the key gate or the app shell. */
    public?: boolean
    /** Platform admin console: its own sign-in and shell. */
    admin?: boolean
    /** Admin pages only owners may open. */
    owner?: boolean
  }
}

// Authentication is an overlay in App.vue rather than a route — a login page
// would be a whole navigation state to guard on every other route, for what is
// one text field. The one exception is /demo (meta.public), which has to work
// before there is any key at all.
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/fleet' },
    {
      path: '/fleet',
      name: 'fleet',
      component: () => import('@/views/FleetDashboard.vue'),
      meta: { title: 'Fleet' },
    },
    {
      path: '/generators/:id',
      name: 'generator',
      component: () => import('@/views/GeneratorDetail.vue'),
      props: true,
      // Replaced with the generator's name once it loads.
      meta: { title: 'Generator' },
    },
    {
      // Tanks are addressable in their own right, not only through the
      // generator that happens to draw on them: a bulk tank belongs to a site
      // and to no single generator, so there is no generator page to hang it
      // off.
      path: '/tanks/:id',
      name: 'tank',
      component: () => import('@/views/TankDetail.vue'),
      props: true,
      // Replaced with the tank's name once it loads.
      meta: { title: 'Tank' },
    },
    {
      // A site is the unit the map pins and the unit fuel is actually delivered
      // to — several tanks and generators share one address.
      path: '/sites/:id',
      name: 'site',
      component: () => import('@/views/SiteDetail.vue'),
      props: true,
      // Replaced with the site's name once it loads.
      meta: { title: 'Site' },
    },
    {
      // Coupon signup. Public: it is how a prospect gets a key in the first
      // place. Signed-in demo users land here too, at the "add" step.
      path: '/demo',
      name: 'demo',
      component: () => import('@/views/demo/DemoWizard.vue'),
      meta: { title: 'Start a demo', public: true },
    },
    {
      path: '/vehicles',
      name: 'vehicles',
      component: () => import('@/views/VehiclesList.vue'),
      meta: { title: 'Tractors' },
    },
    {
      path: '/vehicles/:id',
      name: 'vehicle',
      component: () => import('@/views/VehicleDetail.vue'),
      props: true,
      meta: { title: 'Tractor' },
    },
    // Platform admin console. Lazy chunks: a tenant never downloads them.
    {
      path: '/admin',
      name: 'admin',
      component: () => import('@/views/admin/AdminOverview.vue'),
      meta: { title: 'Admin', admin: true },
    },
    {
      path: '/admin/tenants',
      name: 'admin-tenants',
      component: () => import('@/views/admin/AdminTenants.vue'),
      meta: { title: 'Tenants · Admin', admin: true },
    },
    {
      path: '/admin/tenants/:id',
      name: 'admin-tenant',
      component: () => import('@/views/admin/AdminTenantDetail.vue'),
      props: true,
      meta: { title: 'Tenant · Admin', admin: true },
    },
    {
      path: '/admin/coupons',
      name: 'admin-coupons',
      component: () => import('@/views/admin/AdminCoupons.vue'),
      meta: { title: 'Coupons · Admin', admin: true },
    },
    {
      path: '/admin/coupons/:id',
      name: 'admin-coupon',
      component: () => import('@/views/admin/AdminCouponDetail.vue'),
      props: true,
      meta: { title: 'Coupon · Admin', admin: true },
    },
    {
      path: '/admin/system',
      name: 'admin-system',
      component: () => import('@/views/admin/AdminSystem.vue'),
      meta: { title: 'System · Admin', admin: true },
    },
    {
      path: '/admin/admins',
      name: 'admin-admins',
      component: () => import('@/views/admin/AdminAdmins.vue'),
      meta: { title: 'Admins · Admin', admin: true, owner: true },
    },
    {
      path: '/admin/audit',
      name: 'admin-audit',
      component: () => import('@/views/admin/AdminAudit.vue'),
      meta: { title: 'Audit log · Admin', admin: true },
    },
    {
      path: '/incidents',
      name: 'incidents',
      component: () => import('@/views/IncidentsFeed.vue'),
      meta: { title: 'Incidents' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'notfound',
      component: () => import('@/views/NotFound.vue'),
      meta: { title: 'Not found' },
    },
  ],
  scrollBehavior: (to, from, saved) => saved ?? { top: 0 },
})

/**
 * The title was the Vite scaffold default and never changed, so screen-reader
 * users and anyone scanning browser tabs got the same label on every screen.
 */
export const TITLE_SUFFIX = 'FuelPay'
router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · ${TITLE_SUFFIX}` : TITLE_SUFFIX
})

export default router
