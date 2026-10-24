<script setup>
import Icon from './Icon.vue';
import {fileUrl,imageFile} from '../lib/api.js';
defineProps({files:Array,session:String,available:Set});
</script>
<template><div v-if="files?.length" class="message-attachments"><a v-for="file in files" :key="file.id||file.path" class="message-file" :class="{'is-missing':file.id&&!available.has(file.id)}" :href="!file.id||available.has(file.id)?fileUrl(session,file):undefined" :download="file.path.split('/').at(-1)"><template v-if="file.id&&!available.has(file.id)"><span>{{file.path}}（已清理）</span></template><template v-else><img v-if="imageFile(file)" class="message-image" :src="`/api/sessions/${session}/images/${file.id}`" :alt="file.path" loading="lazy"><Icon v-else name="paperclip"/><span>{{file.path}}</span></template></a></div></template>
