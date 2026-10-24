<script setup>
import {computed} from 'vue';
import {marked} from 'marked';
import DOMPurify from 'dompurify';
const props=defineProps({text:{type:String,default:''}});
const html=computed(()=>{
  const clean=DOMPurify.sanitize(marked.parse(props.text,{gfm:true,breaks:true}),{
    ALLOWED_TAGS:['p','br','strong','em','del','s','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','pre','code','hr','a','table','thead','tbody','tr','th','td','input'],
    ALLOWED_ATTR:['href','title','class','start','type','checked','disabled','align'],ALLOW_DATA_ATTR:false,ALLOW_ARIA_ATTR:false,
  });
  const document=new DOMParser().parseFromString(clean,'text/html');
  for(const link of document.querySelectorAll('a')){
    if(!/^(https?:\/\/|mailto:|#)/i.test(link.getAttribute('href')||''))link.removeAttribute('href');
    else {link.target='_blank';link.rel='noopener noreferrer';}
  }
  for(const input of document.querySelectorAll('input')){input.type='checkbox';input.disabled=true;}
  return document.body.innerHTML;
});
</script>
<template><div class="markdown" v-html="html"/></template>
