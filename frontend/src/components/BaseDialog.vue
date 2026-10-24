<script setup>
import {ref,watch,nextTick,onBeforeUnmount} from 'vue';
defineOptions({inheritAttrs:false});
const props=defineProps({open:Boolean,labelledby:String,busy:Boolean});
const emit=defineEmits(['close']);
const element=ref(null);
watch(()=>props.open,async open=>{await nextTick();const dialog=element.value;if(!dialog)return;if(open&&!dialog.open)dialog.showModal();else if(!open&&dialog.open)dialog.close();},{immediate:true});
function backdrop(event){const r=element.value.getBoundingClientRect();if(!props.busy&&event.target===element.value&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom))emit('close');}
onBeforeUnmount(()=>element.value?.close());
</script>
<template><Teleport to="body"><dialog v-bind="$attrs" ref="element" :aria-labelledby="labelledby" @click="backdrop" @cancel.prevent="!busy && emit('close')" @close="emit('close')"><slot/></dialog></Teleport></template>
