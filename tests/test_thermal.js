'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const componentPath = path.join(root,
    'files/www/luci-static/resources/view/status/include/15_f50_thermal.js');
const aclPath = path.join(root, 'files/usr/share/rpcd/acl.d/luci-f50-thermal.json');
const types = ['apcpu0-thmzone', 'apcpu1-thmzone', 'gpu-thmzone',
    'lte-thmzone', 'nr0-thmzone', 'nr1-thmzone'];
const thermalPath = '/sys/class/thermal';

function publicFixture(options = {}) {
    const indices = [18, 0, 12, 2, 9, 4];
    const files = {};
    const entries = types.map((type, index) => {
        const name = `thermal_zone${indices[index]}`;
        files[`${thermalPath}/${name}/type`] = `${type}\n`;
        files[`${thermalPath}/${name}/temp`] = `${41000 + index * 1000}\n`;
        return { name, type: 'symlink' };
    });
    return { files: { ...files, ...options.files },
        entries: options.entries || entries.reverse(), listError: options.listError };
}

function loadComponent(state) {
    assert.ok(fs.existsSync(componentPath), 'F50 thermal status component must exist');
    const reads = [];
    const adapter = {
        list: async requested => {
            assert.equal(requested, thermalPath);
            if (state.listError) throw state.listError;
            return state.entries;
        },
        read: async requested => {
            reads.push(requested);
            assert.match(requested, /^\/sys\/class\/thermal\/thermal_zone\d+\/(type|temp)$/);
            const value = state.files[requested];
            if (value instanceof Error) throw value;
            if (value === undefined) throw new Error('Not found');
            return value;
        }
    };
    const sandbox = { fs: adapter, baseclass: { extend: spec => spec },
        _: text => text, E: (tag, attributes, children) => ({ tag, attributes, children }) };
    const source = fs.readFileSync(componentPath, 'utf8');
    const component = vm.runInNewContext(`(function() {\n${source}\n})()`, sandbox);
    return { component, reads };
}

test('matches all six types despite shuffled indices and symlink entries', async () => {
    const { component, reads } = loadComponent(publicFixture());
    const data = await component.load();
    assert.equal(data.errors.length, 0);
    assert.deepEqual(Array.from(data.rows, row => row.type), types);
    assert.deepEqual(Array.from(data.rows, row => row.celsius), [41, 42, 43, 44, 45, 46]);
    assert.equal(reads.length, types.length * 2);
    const rendered = JSON.stringify(component.render(data));
    assert.match(rendered, /CPU 测温点 1/);
    assert.match(rendered, /5G NR 测温点 2/);
    assert.match(rendered, /非机身外壳温度/);
    assert.match(rendered, /41\.0 °C/);
});

test('missing type remains visible as missing, never substituted by zone number', async () => {
    const fixture = publicFixture({ files: {
        [`${thermalPath}/thermal_zone18/type`]: 'other-sensor\n' } });
    const { component } = loadComponent(fixture);
    const data = await component.load();
    assert.equal(data.rows[0].celsius, null);
    assert.match(data.rows[0].error, /未发现/);
    assert.match(JSON.stringify(component.render(data)), /未发现/);
});

test('temperature read failure is explicit and other sensors remain available', async () => {
    const fixture = publicFixture({ files: {
        [`${thermalPath}/thermal_zone12/temp`]: new Error('Permission denied') } });
    const { component } = loadComponent(fixture);
    const data = await component.load();
    assert.equal(data.rows[2].celsius, null);
    assert.match(data.rows[2].error, /Permission denied/);
    assert.equal(data.rows[0].celsius, 41);
});

test('duplicate type is ambiguous even if both readings are valid', async () => {
    const fixture = publicFixture({ files: {
        [`${thermalPath}/thermal_zone4/type`]: 'apcpu0-thmzone\n' } });
    const { component, reads } = loadComponent(fixture);
    const data = await component.load();
    assert.equal(data.rows[0].celsius, null);
    assert.match(data.rows[0].error, /重复/);
    assert.ok(!reads.includes(`${thermalPath}/thermal_zone18/temp`));
});

test('empty, NaN, partial numbers and unsafe integers are rejected', async () => {
    for (const invalid of ['', ' \n', 'NaN', '43000junk', '4e4', '9007199254740993']) {
        const fixture = publicFixture({ files: {
            [`${thermalPath}/thermal_zone18/temp`]: invalid } });
        const { component } = loadComponent(fixture);
        const data = await component.load();
        assert.equal(data.rows[0].celsius, null, invalid);
        assert.match(data.rows[0].error, /无效温度/, invalid);
    }
});

test('zero and negative integer temperatures are valid millidegrees', async () => {
    const fixture = publicFixture({ files: {
        [`${thermalPath}/thermal_zone18/temp`]: '0\n',
        [`${thermalPath}/thermal_zone0/temp`]: '-1250\n' } });
    const { component } = loadComponent(fixture);
    const data = await component.load();
    assert.equal(data.rows[0].celsius, 0);
    assert.equal(data.rows[1].celsius, -1.25);
});

test('enumeration failure resolves to explicit data and next poll can recover', async () => {
    const fixture = publicFixture({ listError: new Error('Permission denied') });
    const { component } = loadComponent(fixture);
    const failed = await component.load();
    assert.match(failed.errors.join(' '), /Permission denied/);
    assert.ok(failed.rows.every(row => row.celsius === null));
    fixture.listError = null;
    const recovered = await component.load();
    assert.equal(recovered.errors.length, 0);
    assert.equal(recovered.rows[0].celsius, 41);
});

test('type read failure is visible without hiding other sensor rows', async () => {
    const fixture = publicFixture({ files: {
        [`${thermalPath}/thermal_zone18/type`]: new Error('I/O error') } });
    const { component } = loadComponent(fixture);
    const data = await component.load();
    assert.match(data.errors.join(' '), /thermal_zone18.*I\/O error/);
    assert.equal(data.rows[1].celsius, 42);
});

test('a failed fresh poll cannot reuse the previous successful temperature', async () => {
    const fixture = publicFixture();
    const { component } = loadComponent(fixture);
    assert.equal((await component.load()).rows[0].celsius, 41);
    fixture.files[`${thermalPath}/thermal_zone18/temp`] = new Error('Read failed');
    const failed = await component.load();
    assert.equal(failed.rows[0].celsius, null);
    assert.match(failed.rows[0].error, /Read failed/);
});

test('non-zone entries cannot produce unexpected file reads', async () => {
    const fixture = publicFixture({ entries: [
        { name: '../secret', type: 'directory' }, { name: 'cooling_device0', type: 'symlink' }
    ] });
    const { component, reads } = loadComponent(fixture);
    const data = await component.load();
    assert.equal(reads.length, 0);
    assert.ok(data.rows.every(row => row.celsius === null));
});

test('ACL grants only thermal list/type/temp reads and no command execution', () => {
    assert.ok(fs.existsSync(aclPath), 'F50 thermal read-only ACL must exist');
    const acl = JSON.parse(fs.readFileSync(aclPath, 'utf8'))['luci-f50-thermal'];
    assert.equal(acl.write, undefined);
    assert.deepEqual(acl.read.ubus, { file: ['list', 'read'] });
    assert.deepEqual(acl.read.file, {
        '/sys/class/thermal': ['list'],
        '/sys/class/thermal/thermal_zone[0-9]*/type': ['read'],
        '/sys/class/thermal/thermal_zone[0-9]*/temp': ['read']
    });
});
