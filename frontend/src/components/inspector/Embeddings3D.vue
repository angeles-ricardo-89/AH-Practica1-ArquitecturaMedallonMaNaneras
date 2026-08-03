<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import * as echarts from 'echarts'
import 'echarts-gl'
import type { Embedding3DPoint } from '../../api/embeddings'
import { useDashboardStore } from '../../stores/dashboard'
import type { ClusterPoint } from '../../api/clusters'

const props = withDefaults(defineProps<{
  points: Embedding3DPoint[]
  mode?: 'full' | 'filtered'
}>(), {
  mode: 'full',
})

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

const noiseColor = 'rgba(168, 162, 158, 0.3)'

const chartData = computed(() => {
  return props.points.map((p) => {
    // En modo filtered usamos cluster_id directo del punto (viene de SourceChunk).
    // En modo full hacemos lookup por chunk_key en el universo de clusters.
    let clusterId: number | undefined
    let pertenencia = 0
    if (props.mode === 'filtered' && p.cluster_id !== undefined) {
      clusterId = p.cluster_id
    } else {
      const cp = clusterPointMap.value.get(p.chunk_key)
      if (cp) {
        clusterId = cp.cluster_id
        pertenencia = cp.pertenencia
      }
    }

    let color: string
    let opacity: number
    let size: number

    if (props.mode === 'filtered') {
      // Modo filtrado: colores de cluster, siempre visibles
      if (clusterId !== undefined && clusterId >= 0) {
        color = dashboardStore.getClusterColor(clusterId)
        opacity = 1.0
      } else if (clusterId === -1) {
        color = '#A8A29E'
        opacity = 0.5
      } else {
        color = '#A8A29E'
        opacity = 1.0
      }
      size = 8
    } else {
      // Modo full: comportamiento original
      if (clusterId !== undefined) {
        if (clusterId === -1) {
          color = noiseColor
          opacity = 0.3
        } else {
          color = dashboardStore.getClusterColor(clusterId)
          opacity = 0.7
        }
      } else {
        color = '#A8A29E'
        opacity = 0.6
      }
      size = 6
    }

    let name = p.chunk_key
    if (clusterId !== undefined && clusterId >= 0) {
      const label = dashboardStore.clusterData?.clusters.find(c => c.cluster_id === clusterId)?.label
      name = label ? `${label} (${pertenencia.toFixed(2)})` : `Cluster ${clusterId} (${pertenencia.toFixed(2)})`
    } else if (clusterId === -1) {
      name = 'Ruido'
    }

    return {
      value: [p.x, p.y, p.z],
      itemStyle: { color, opacity },
      symbolSize: size,
      name,
    }
  })
})

const visibleClusters = computed(() => {
  if (props.mode !== 'filtered' || !dashboardStore.clusterData) return []
  const presentIds = new Set<number>()
  for (const p of props.points) {
    const cid = p.cluster_id !== undefined ? p.cluster_id : clusterPointMap.value.get(p.chunk_key)?.cluster_id
    if (cid !== undefined && cid >= 0) {
      presentIds.add(cid)
    }
  }
  return dashboardStore.clusterData.clusters.filter(c => presentIds.has(c.cluster_id))
})

const visibleNoiseCount = computed(() => {
  if (props.mode !== 'filtered') return 0
  return props.points.filter(p => {
    const cid = p.cluster_id !== undefined ? p.cluster_id : clusterPointMap.value.get(p.chunk_key)?.cluster_id
    return cid === -1
  }).length
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
      symbolSize: (data: any, params: any) => {
        return chartData.value[params?.dataIndex]?.symbolSize ?? 6
      },
      itemStyle: { borderWidth: 0 },
      emphasis: { itemStyle: { color: '#7F1D1D' } },
      animation: true,
      animationDuration: 600,
      animationDurationUpdate: 600,
      animationEasing: 'cubicInOut',
      animationEasingUpdate: 'cubicInOut',
    }],
  })
}

function handleResize() {
  myChart?.resize()
}

watch(() => props.points, updateChart, { deep: true })
watch(() => props.mode, updateChart)
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
      <template v-if="mode === 'full'">
        <div class="flex items-center gap-1">
          <span class="w-2 h-2 rounded-full bg-stone-400" />
          <span>chunks neutros</span>
        </div>
        <div v-if="dashboardStore.clusterData && dashboardStore.clusterData.noise_count > 0" class="flex items-center gap-1">
          <span class="w-2 h-2 rounded-full opacity-30" style="background-color: rgba(168, 162, 158, 0.3);" />
          <span>ruido ({{ dashboardStore.clusterData.noise_count }})</span>
        </div>
      </template>
      <template v-else>
        <div
          v-for="cluster in visibleClusters"
          :key="cluster.cluster_id"
          class="flex items-center gap-1"
        >
          <span class="w-2 h-2 rounded-full" :style="{ backgroundColor: dashboardStore.getClusterColor(cluster.cluster_id) }" />
          <span>{{ cluster.label || `Cluster ${cluster.cluster_id}` }}</span>
        </div>
        <div v-if="visibleNoiseCount > 0" class="flex items-center gap-1">
          <span class="w-2 h-2 rounded-full opacity-50" style="background-color: #A8A29E;" />
          <span>ruido ({{ visibleNoiseCount }})</span>
        </div>
      </template>
    </div>
  </div>
</template>
