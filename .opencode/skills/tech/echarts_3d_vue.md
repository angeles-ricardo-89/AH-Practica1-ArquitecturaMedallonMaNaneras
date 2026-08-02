# Skill: ECharts 3D Vue
**Domain**: ECharts 3D visualization in Vue 3.
**Tech**: ECharts, ECharts-GL, Vue 3 (Composition API), TypeScript.

## Overview
Use this skill when implementing 3D visualizations (e.g., 3D Scatter Plots, Embeddings) within a Vue 3 component.

## Implementation Patterns

### 1. Basic 3D Component Structure
Always use the Composition API and ensure the chart instance is cleaned up.

```typescript
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import * as echarts from 'echarts';
import 'echarts-gl'; // Required for 3D features

const chartRef = ref<HTMLElement | null>(null);
let myChart: echarts.ECharts | null = null;

onMounted(() => {
  if (chartRef.value) {
    myChart = echarts.init(chartRef.value);
    // Initialize chart with options
    myChart.setOption({
      // ... configuration ...
    });
  }
});

onUnmounted(() => {
  myChart?.dispose();
});
</script>

<template>
  <div ref="chartRef" style="width: 100%; height: 400px;"></div>
</template>
```

### 2. Updating Data Dynamically
To update the chart (e.g., highlighting points), use `setOption` with only the changed data.

```typescript
const updateChart = (newData: any) => {
  myChart?.setOption({
    series: [{
      data: newData
    }]
  });
};
```

### 3. Handling Window Resizing
Ensure the chart scales with its container.

```typescript
const handleResize = () => {
  myChart?.resize();
};

onMounted(() => {
  // ... init ...
  window.addEventListener('resize', handleResize);
});

onUnmounted(() => {
  window.removeEventListener('resize', handleResize);
});
```

## Best Practices
- **Performance**: For large datasets (e.g., 10k+ points), use `scatter3D` with `large: true` if available.
- **Cleanup**: Always call `dispose()` to prevent memory leaks.
- **TypeScript**: Use `echarts.ECharts` for typing the instance.
- **3D Specifics**: Ensure `echarts-gl` is imported.

## Common Mistakes
- Forgetting to import `echarts-gl`.
- Not calling `dispose()` on unmount.
- Re-initializing the chart instead of using `setOption` for updates.
