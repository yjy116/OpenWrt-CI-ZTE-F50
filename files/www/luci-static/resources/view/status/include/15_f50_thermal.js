'use strict';
'require baseclass';
'require fs';

const THERMAL_PATH = '/sys/class/thermal';
const MILLICELSIUS_PER_CELSIUS = 1000;
const SENSORS = [
    { type: 'apcpu0-thmzone', label: 'CPU 测温点 1' },
    { type: 'apcpu1-thmzone', label: 'CPU 测温点 2' },
    { type: 'gpu-thmzone', label: 'GPU' },
    { type: 'lte-thmzone', label: 'LTE' },
    { type: 'nr0-thmzone', label: '5G NR 测温点 1' },
    { type: 'nr1-thmzone', label: '5G NR 测温点 2' }
];

function errorText(error) {
    return error && error.message ? String(error.message) : String(error);
}

function failedSensor(sensor, error) {
    return { type: sensor.type, label: sensor.label, celsius: null, error: error };
}

async function readZoneType(zone) {
    try {
        const raw = await fs.read(THERMAL_PATH + '/' + zone + '/type');
        if (typeof raw !== 'string' || raw.trim() === '')
            throw new Error('传感器类型为空或格式无效');
        return { zone: zone, type: raw.trim(), error: null };
    }
    catch (error) {
        return { zone: zone, type: null,
            error: zone + ' 类型读取失败：' + errorText(error) };
    }
}

function temperatureCelsius(raw) {
    const text = typeof raw === 'string' ? raw.trim() : '';
    if (!/^-?\d+$/.test(text) || !Number.isSafeInteger(Number(text)))
        throw new Error('无效温度：应为毫摄氏度整数');
    return Number(text) / MILLICELSIUS_PER_CELSIUS;
}

async function readSensor(sensor, zones) {
    const matches = zones.filter(zone => zone.type === sensor.type);
    if (matches.length === 0)
        return failedSensor(sensor, '未发现传感器：' + sensor.type);
    if (matches.length !== 1)
        return failedSensor(sensor, '传感器类型重复：' + sensor.type);
    try {
        const raw = await fs.read(THERMAL_PATH + '/' + matches[0].zone + '/temp');
        return { type: sensor.type, label: sensor.label,
            celsius: temperatureCelsius(raw), error: null };
    }
    catch (error) {
        return failedSensor(sensor, '温度读取失败：' + errorText(error));
    }
}

async function loadTemperatures() {
    let entries;
    try {
        entries = await fs.list(THERMAL_PATH);
        if (!Array.isArray(entries))
            throw new Error('传感器列表格式无效');
    }
    catch (error) {
        return { errors: ['传感器枚举失败：' + errorText(error)],
            rows: SENSORS.map(sensor => failedSensor(sensor, '无法读取传感器列表')) };
    }
    // Sysfs class entries are symlinks. Identity comes from type, never the index.
    const names = entries.filter(entry => entry && /^thermal_zone\d+$/.test(entry.name))
        .map(entry => entry.name);
    const zones = await Promise.all(names.map(readZoneType));
    return { errors: zones.filter(zone => zone.error).map(zone => zone.error),
        rows: await Promise.all(SENSORS.map(sensor => readSensor(sensor, zones))) };
}

function sensorRow(sensor) {
    const value = sensor.error || sensor.celsius.toFixed(1) + ' °C';
    return E('tr', { 'class': 'tr' }, [
        E('td', { 'class': 'td left', 'width': '33%', 'title': sensor.type }, [sensor.label]),
        E('td', { 'class': 'td left' }, [value])
    ]);
}

return baseclass.extend({
    title: 'F50 芯片温度',
    // Return errors as visible data: the overview permanently hides rejected includes.
    load: loadTemperatures,
    render: function(data) {
        const errors = data.errors.map(error => E('p', {}, [error]));
        return E('div', {}, [
            E('p', { 'class': 'cbi-section-descr' }, [
                '芯片内部测温点，非机身外壳温度。数值随概览页自动刷新。'
            ]),
            E('div', { 'role': 'status' }, errors),
            E('table', { 'class': 'table' }, data.rows.map(sensorRow))
        ]);
    }
});
