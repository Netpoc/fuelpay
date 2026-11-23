/**
 * Tree-shaken ECharts registration.
 *
 * Importing the `echarts` barrel pulls roughly a megabyte; registering only
 * what we draw keeps it near 70kB gzipped. Add to these lists when a chart
 * needs something new — a missing component fails at render with a bare
 * "series type not registered", which is easy to misread as a data problem.
 */
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components'

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  MarkAreaComponent,
])
