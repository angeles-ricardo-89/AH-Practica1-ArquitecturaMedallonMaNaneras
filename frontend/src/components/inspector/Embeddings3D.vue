<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import * as echarts from 'echarts'
import 'echarts-gl'
import type { Embedding3DPoint } from '../../api/embeddings'
import { useDashboardStore } from '../../stores/dashboard'
import type { ClusterPoint } from '../../api/clusters'

const props = defineProps<{
  points: Embedding3DPoint[]
  highlightedChunks: string[]
}>()

const dashboardStore = useDashboardStore()

const chartRef = ref<HTMLElement | null>(null)
let myChart: echarts.ECharts | null = null

const clusterPointMap = computed(() => {
  const map = new Map<string, ClusterPoint>()
  if (!dashboardStore.clusterData) return map
  for (const p of dashboardStore.clusterData.points) {
    map.set(p.chunk_key, p)
  }
  return map
})

const chartData = computed(() => {
  const noiseColor = 'rgba(168, 162, 158, 0.3)'

  return props.points.map((p) => {
    const cp = clusterPointMap.value.get(p.chunk_key)
    const isHighlighted = props.highlightedChunks.includes(p.chunk_key)

    let color: string
    let opacity: number

    if (isHighlighted) {
      color = '#7F1D1D'
      opacity = 1.0
    } else if (cp) {
      if (cp.cluster_id === -1) {
        color = noiseColor
        opacity = 0.3
      } else {
        color = dashboardStore.clusterColorMap.get(cp.cluster_id) ?? '#A8A29E'
        opacity = 0.7
      }
    } else {
      color = '#A8A29E'
      opacity = 0.6
    }

    let name = p.chunk_key
    if (cp && cp.cluster_id >= 0) {
      const label = dashboardStore.clusterData?.clusters.find(c => c.cluster_id === cp.cluster_id)?.label
      name = label ? `${label} (${cp.pertenencia.toFixed(2)})` : `Cluster ${cp.cluster_id} (${cp.pertenencia.toFixed(2)})`
    } else if (cp && cp.cluster_id === -1) {
      name = 'Ruido'
    }

    return {
      value: [p.x, p.y, p.z],
      itemStyle: { color, opacity },
      name,
    }
  })
})

function initChart() {
  if (!chartRef.value) return
  myChart = echarts.init(chartRef.value)
  updateChart()

  window.addEventListener('resize', handleResize)
}

function updateChart() {
  if (!myChart) return
  myChart.setOption({
    tooltip: {
      show: true,
      formatter: (params: any) => {
        const d = params.data || {}
        return d.name || ''
      },
      textStyle: { fontSize: 10 },
    },
    xAxis3D: {
      type: 'value', name: '',
      axisLine: { lineStyle: { color: '#D6D3D1' } },
      axisLabel: { show: false },
      splitLine: { show: false },
    },
    yAxis3D: {
      type: 'value', name: '',
      axisLine: { lineStyle: { color: '#D6D3D1' } },
      axisLabel: { show: false },
      splitLine: { show: false },
    },
    zAxis3D: {
      type: 'value', name: '',
      axisLine: { lineStyle: { color: '#D6D3D1' } },
      axisLabel: { show: false },
      splitLine: { show: false },
    },
    grid3D: {
      boxWidth: 100, boxHeight: 100, boxDepth: 100,
      viewControl: {
        autoRotate: false,
        projection: 'perspective',
        rotateSensitivity: 1,
        zoomSensitivity: 1,
        panSensitivity: 0,
      },
      light: {
        main: { intensity: 1.2, shadow: false },
        ambient: { intensity: 0.3 },
      },
    },
    series: [{
      type: 'scatter3D',
      data: chartData.value,
      symbolSize: 6,
      itemStyle: { borderWidth: 0 },
      emphasis: { itemStyle: { color: '#7F1D1D' } },
    }],
  })
}

function handleResize() {
  myChart?.resize()
}

watch(() => props.points, updateChart, { deep: true })
watch(() => props.highlightedChunks, updateChart, { deep: true })
watch(() => dashboardStore.clusterData, updateChart, { deep: true })

onMounted(initChart)
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  myChart?.dispose()
  myChart = null
})
</script>

<template>
  <div class="bg-white border border-stone-200 rounded-2xl p-4 flex flex-col">
    <div class="flex items-center justify-between mb-2">
      <h3 class="text-sm font-bold text-stone-950">Embeddings 3D</h3>
      <span class="text-[10px] text-stone-400">rotar + zoom limitado</span>
    </div>
    <div ref="chartRef" class="w-full h-48" />
    <div class="flex items-center gap-3 mt-2 text-[10px] text-stone-500 flex-wrap">
      <div class="flex items-center gap-1">
        <span class="w-2 h-2 rounded-full bg-stone-400" />
        <span>chunks neutros</span>
      </div>
      <div class="flex items-center gap-1">
        <span class="w-2 h-2 rounded-full bg-red-900" />
        <span>chunks citados</span>
      </div>
      <div v-if="dashboardStore.clusterData && dashboardStore.clusterData.noise_count > 0" class="flex items-center gap-1">
        <span class="w-2 h-2 rounded-full opacity-30" style="background-color: rgba(168, 162, 158, 0.3);" />
        <span>ruido ({{ dashboardStore.clusterData.noise_count }})</span>
      </div>
    </div>
  </div>
</template>
