// 图表更新器
const chartUpdater = (prop, value) => {
    switch (prop) {
        case 'cpu_usage':
            updateCpuChart && updateCpuChart(value);
            break
        case 'realtime_rx_thrpt':
            updateNetworkChart && updateNetworkChart(value)
            break
        case 'cpu_temp':
            updateTempChart && updateTempChart(value)
            break
        case 'mem_usage':
            updateMemChart && updateMemChart(value)
            break
        case 'cpuFreqInfo':
            if (value) {
                const cpuFreqList = document.querySelector('#cpuFreqList')
                let html = ''
                for (let i = 0; value[`cpu${i}`] != undefined && value[`cpu${i}`] != null; i++) {
                    let cur = String(value[`cpu${i}`].cur)
                    let cur_origin = String(value[`cpu${i}`].cur)
                    let max = String(value[`cpu${i}`].max)
                    // 通过使用率表判断核心启用状态
                    let usgList = window.UFI_DATA.cpuUsageInfo
                    if (usgList) {
                        if (!usgList[`cpu${i}`]) {
                            cur_origin = 0
                        }
                    }
                    if (cur.length == 1) cur = `&nbsp;&nbsp;&nbsp;${cur}`
                    else if (cur.length == 2) cur = `&nbsp;&nbsp;${cur}`
                    else if (cur.length == 3) cur = `&nbsp;${cur}`
                    const btnColor = getCssVariableColor('--dark-btn-color-active')
                    html += `${kano_parseSignalBar(cur_origin, 0, max, max * 0.9, max * 0.9, {
                        g: '#ffa5008f',
                        o: '#ffa5008f',
                        r: btnColor
                    })}`

                }
                cpuFreqList.innerHTML = html
            }
            break
        case 'cpuUsageInfo':
            updateCpuCoreChart && updateCpuCoreChart(value)
            break
        case 'memInfo':
            if (value) {
                const memInfo = document.querySelector('#memInfo')
                memInfo.innerHTML = `<div>${t('ram_all')}：${formatBytes(value['mem_total_kb'] * 1024)}</div>
                <div>${t('ram_available')}：${formatBytes(value['mem_available_kb'] * 1024)}</div>
                <div>${t('ram_used')}：${formatBytes(value['mem_used_kb'] * 1024)}(${Math.round(value['mem_usage_percent'])}%)</div>
                <div>${t('all_swap')}：${formatBytes(value['swap_total_kb'] * 1024)}</div>
                <div>${t('swap_used')}：${formatBytes(value['swap_used_kb'] * 1024)}(${Math.round(value['swap_usage_percent'])}%)</div>
                <div>${t('swap_available')}：${formatBytes(value['swap_free_kb'] * 1024)}</div>`
            }
            break
        case 'cpu_temp_list':
            if (value) {
                value?.sort((a, b) => {
                    const charA = a?.type?.charAt(0) || '';
                    const charB = b?.type?.charAt(0) || '';
                    return charA.localeCompare(charB);
                });
                const html = value?.map(item => {
                    return `<div>${item?.type?.replace('-thmzone', '')}: ${(Number(item?.temp) / 1000).toFixed(2)} ℃</div>`
                })
                const cpuTempInfo = document.querySelector('#cpuTempInfo')
                cpuTempInfo.innerHTML = html.join("")
            }
            break
    }
}

const MAX_length = 20
const ANI_DURATION = 300

//cpu占用
const updateCpuChart = (() => {
    const canvas = document.getElementById('kanoCpuChart');
    const ctx = canvas.getContext('2d');
    const labels = Array(MAX_length).fill('0')
    const data = Array(MAX_length).fill(0)

    Chart.register(centerTextPlugin);
    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data,
                tension: 0.5,
                pointRadius: 0,
                fill: true,
                backgroundColor: getCssVariableColor('--dark-btn-color-active'),
                borderColor: getCssVariableColor('--dark-btn-color-active'),
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: ANI_DURATION,    // 0.5秒动画
                easing: 'easeOutQuad'  // 自然缓动效果
            },
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false }
                },
                y: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false },
                    max: 100,
                    min: 0
                }
            }
        }
    });

    return (value) => {
        if (value != undefined || value != null) {
            chart.options.plugins.centerText.text = [
                { text: `CPU: ${Math.floor(value)} % ` }
            ]
            labels.length > MAX_length && labels.shift()
            data.length > MAX_length && data.shift()

            labels.push(Number(labels[labels.length - 1]) + 1)
            data.push(Number(value))

            chart.data.datasets[0].backgroundColor = getCssVariableColor('--dark-btn-color-active');
            chart.data.datasets[0].borderColor = getCssVariableColor('--dark-btn-color-active');
            chart.update()
        }
    }
})()

//cpu核心占用
const updateCpuCoreChart = (() => {
    const canvas = document.getElementById('kanoCpuCoreChart');
    const ctx = canvas.getContext('2d');
    const labels = ['核心1', '核心2', '核心3', '核心4', '核心5', '核心6', '核心7', '核心8']
    const data = Array(8).fill(0)

    Chart.register(centerTextPlugin);
    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data,
                tension: 0.5,
                pointRadius: 0,
                fill: true,
                backgroundColor: getCssVariableColor('--dark-btn-color-active'),
                borderColor: getCssVariableColor('--dark-btn-color-active'),
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: ANI_DURATION,    // 0.5秒动画
                easing: 'easeOutQuad'  // 自然缓动效果
            },
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false }
                },
                y: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false },
                    max: 100,
                    min: 0
                }
            }
        }
    });

    return (value) => {
        if (value != undefined || value != null) {
            for (let index = 0; index < 8; index++) {
                if (value[`cpu${index}`] != undefined) {
                    data[index] = Math.round(value[`cpu${index}`])
                } else {
                    data[index] = 0
                }
            }
            chart.data.datasets[0].backgroundColor = getCssVariableColor('--dark-btn-color-active');
            chart.data.datasets[0].borderColor = getCssVariableColor('--dark-btn-color-active');
            chart.update()
        }
    }
})()

//内存占用
const updateMemChart = (() => {
    const canvas = document.getElementById('kanoMemChart');
    const ctx = canvas.getContext('2d');
    const labels = Array(MAX_length).fill('0')
    const data = Array(MAX_length).fill(0)

    Chart.register(centerTextPlugin);
    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data,
                borderColor: getCssVariableColor('--dark-btn-color-active'),
                tension: 0.5,
                pointRadius: 0,
                fill: false,
                borderWidth: 2,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: ANI_DURATION,    // 0.5秒动画
                easing: 'easeOutQuad'  // 自然缓动效果
            },
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false }
                },
                y: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false },
                    max: 100,
                    min: 0
                }
            }
        }
    });

    return (value) => {
        if (value != undefined || value != null) {
            chart.options.plugins.centerText.text = [
                { text: `${t('ram')}: ${Math.floor(value)} % ` }
            ]

            let newLabels = [...labels]
            let newData = [...data]

            newLabels.push(Number(newLabels[newLabels.length - 1]) + 1)
            newData.push(Number(value))

            newLabels.length > MAX_length && newLabels.shift()
            newData.length > MAX_length && newData.shift()

            labels.forEach((_, index) => {
                labels[index] = newLabels[index]
            })
            data.forEach((_, index) => {
                data[index] = newData[index]
            })
            chart.data.datasets[0].backgroundColor = getCssVariableColor('--dark-btn-color-active');
            chart.data.datasets[0].borderColor = getCssVariableColor('--dark-btn-color-active');
            chart.update()
        }
    }
})()

// CPU温度图表
const updateTempChart = (() => {
    const canvas = document.getElementById('kanoTempChart');
    const ctx = canvas.getContext('2d');
    const labels = Array(MAX_length).fill('0')
    const data = Array(MAX_length).fill(0)

    Chart.register(centerTextPlugin);
    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data,
                borderColor: getCssVariableColor('--dark-btn-color-active'),
                tension: 0.5,
                pointRadius: 0,
                borderWidth: 2,
                fill: false
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: ANI_DURATION,
                easing: 'easeOutQuad',
            },
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false }
                },
                y: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false },
                    max: 110,
                    min: 0
                }
            }
        }
    });

    return (value) => {
        if (value != undefined || value != null) {
            chart.options.plugins.centerText.text = [
                { text: `${t('temperature')}: ${String(Number(value / 1000).toFixed(2))}℃` }
            ]
            let newLabels = [...labels]
            let newData = [...data]

            newLabels.push(Number(newLabels[newLabels.length - 1]) + 1)
            newData.push(Number(value / 1000).toFixed(2))

            newLabels.length > MAX_length && newLabels.shift()
            newData.length > MAX_length && newData.shift()

            labels.forEach((_, index) => {
                labels[index] = newLabels[index]
            })
            data.forEach((_, index) => {
                data[index] = newData[index]
            })
            chart.data.datasets[0].backgroundColor = getCssVariableColor('--dark-btn-color-active');
            chart.data.datasets[0].borderColor = getCssVariableColor('--dark-btn-color-active');
            chart.update()
        }
    }
})()

//网速图表
const updateNetworkChart = (() => {
    const canvas = document.getElementById('kanoNetChart');
    const ctx = canvas.getContext('2d');
    const labels = Array(MAX_length).fill('0')
    const dataDL = Array(MAX_length).fill(0)
    const dataUL = Array(MAX_length).fill(0)

    Chart.register(centerTextPlugin);
    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'DL',
                data: dataDL,
                borderColor: getCssVariableColor('--dark-btn-color-active'),
                tension: 0.5,
                pointRadius: 0,
                yAxisID: 'y',
                fill: false,
                borderWidth: 2
            }, {
                label: 'UL',
                data: dataUL,
                borderColor: 'pink',
                tension: 0.5,
                pointRadius: 0,
                yAxisID: 'y1',
                fill: false,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: ANI_DURATION,    // 0.5秒动画
                easing: 'easeOutQuad'  // 自然缓动效果
            },
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false }
                },
                y: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false },
                    suggestedMax: 38400,
                    min: 0
                },
                y1: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false },
                    suggestedMax: 38400,
                    min: 0
                }
            }
        }
    });

    return (value) => {
        if (value != undefined || value != null) {
            setTimeout(() => {
                let UL = window?.UFI_DATA?.realtime_tx_thrpt
                if (UL != undefined) {
                    chart.options.plugins.centerText.text = [
                        { text: `↑ ${formatBytes(UL)}/S`, color: 'pink' },
                        {
                            text: `↓ ${formatBytes(value)}/S`
                        }
                    ];

                    let newLabels = [...labels]
                    let newDataDL = [...dataDL]
                    let newDataUL = [...dataUL]

                    newLabels.push(Number(labels[labels.length - 1]) + 1)
                    newDataDL.push(value / 1024)
                    newDataUL.push(UL / 1024)

                    newLabels.length > MAX_length && newLabels.shift()
                    newDataDL.length > MAX_length && newDataDL.shift()
                    newDataUL.length > MAX_length && newDataUL.shift()

                    labels.forEach((_, index) => {
                        labels[index] = newLabels[index]
                    })
                    dataDL.forEach((_, index) => {
                        dataDL[index] = newDataDL[index]
                    })
                    dataUL.forEach((_, index) => {
                        dataUL[index] = newDataUL[index]
                    })
                    chart.data.datasets[0].backgroundColor = getCssVariableColor('--dark-btn-color-active');
                    chart.data.datasets[0].borderColor = getCssVariableColor('--dark-btn-color-active');
                    chart.update()
                }
            }, 1);
        }
    }
})()

//流量使用情况图表
const updateDataHistoryChart = (() => {
    const canvas = document.getElementById('kanoDataHistoryChart');
    const ctx = canvas.getContext('2d');
    const labels = Array(MAX_length).fill('')
    const data = Array(MAX_length).fill(0)

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data,
                tension: 0.5,
                pointRadius: 4,
                pointBorderWidth: 3,
                fill: true,
                pointBackgroundColor: getTextColor(),
                pointBorderColor: getCssVariableColor('--dark-btn-color-active'),
                backgroundColor: getCssVariableColor('--dark-btn-color-active'),
                borderColor: getCssVariableColor('--dark-btn-color-active'),
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: ANI_DURATION,    // 0.5秒动画
                easing: 'easeOutQuad'  // 自然缓动效果
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            return formatBytes(ctx.raw);
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        maxRotation: 0,
                        minRotation: 0,
                        display: true,
                        color: getTextColor(),
                        font: {
                            size: 10
                        }
                    },
                    border: { display: false }
                },
                y: {
                    grid: { display: false },
                    ticks: { display: false },
                    border: { display: false },
                    max: 1024 * 1024 * 1024,
                    min: 0
                }
            }
        }
    });

    return ({ items }) => {
        if (!items || items.length === 0) {
            //清空数据
            chart.data.labels = Array(MAX_length).fill('');
            chart.data.datasets[0].data = Array(MAX_length).fill(0);
            chart.update();
            return;
        }

        const newLabels = items.map(({ date }) => `${date.split('-')[1]}-${date.split('-')[2]}`);
        const newData = items.map(u => Number(u.usage) || 0);
        const max = Math.max(...newData);

        chart.data.labels = newLabels;
        chart.data.datasets[0].data = newData;
        chart.data.datasets[0].backgroundColor = getCssVariableColor('--dark-btn-color-active');
        chart.data.datasets[0].borderColor = getCssVariableColor('--dark-btn-color-active');
        chart.data.datasets[0].pointBackgroundColor = getTextColor()
        chart.data.datasets[0].pointBorderColor = getCssVariableColor('--dark-btn-color-active')
        //数量太密集了就缩小点点
        if (items.length >= 15) {
            chart.data.datasets[0].pointRadius = 0
            chart.data.datasets[0].pointBorderWidth = 0
        } else {
            chart.data.datasets[0].pointRadius = 4
            chart.data.datasets[0].pointBorderWidth = 3
        }

        chart.options.scales.y.max = Math.ceil(max * 1.1);
        chart.update();
    };
})()