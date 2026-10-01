import test from 'node:test';
import assert from 'node:assert/strict';
import {putOperation, projectedValue, inputValue} from '../src/state.mjs';
test('edits coalesce per exact path without losing false or zero',()=>{
  let ops=putOperation([],{op:'value',node:'query',path:['Limit'],value:3});
  ops=putOperation(ops,{op:'value',node:'query',path:['Limit'],value:0});
  ops=putOperation(ops,{op:'value',node:'query',path:['enabled'],value:false});
  assert.equal(ops.length,2);
  assert.equal(projectedValue({path:['Limit'],value:30},ops,'query'),0);
  assert.equal(projectedValue({path:['enabled'],value:true},ops,'query'),false);
  assert.equal(projectedValue({path:['Limit'],value:30},ops,'other'),30);
});
test('distinct bindings and graph operations stay in order',()=>{
  let ops=putOperation([],{op:'bind',node:'invoke',target:'Payload.one',source:'params.one'});
  ops=putOperation(ops,{op:'bind',node:'invoke',target:'Payload.two',source:'params.two'});
  ops=putOperation(ops,{op:'connect',node:'query',target:'invoke'});
  assert.equal(ops.length,3);
});
test('empty numeric fields are not converted to zero',()=>{
  assert.equal(inputValue('integer',''), '');
  assert.equal(inputValue('integer','0'), 0);
  assert.equal(inputValue('number','1.5'), 1.5);
  assert.equal(inputValue('string','001'), '001');
  assert.equal(inputValue('number','1e999'), '1e999');
});
