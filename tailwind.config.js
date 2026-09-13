/** Build-time Tailwind config. Must mirror the `tailwind.config = {...}` block in
 *  client_dashboard.html's <head> (the build strips that block and inlines this output). */
module.exports = {
  content: ['./client_dashboard.html'],
  theme: { extend: {
    colors: {
      ground:'#F4F5F2', surface:'#FFFFFF', surface2:'#F9FAF8',
      ink:'#163A4A', ink2:'#3F5560', muted:'#7E8F96', faint:'#B9C4C8',
      line:'#DDE2E0', line2:'#EBEEEC',
      accent:'#0F8B9F', accentInk:'#0B6E7E', accentTint:'#E3F1F4', accentTint2:'#C9E5EA',
      attn:'#D2623A', attnTint:'#FBE9E2', ghost:'#9AA6AB',
    },
    fontFamily: {
      h: ['Archivo','Arial','sans-serif'],
      b: ['"IBM Plex Sans"','Arial','sans-serif'],
      m: ['"IBM Plex Mono"','Consolas','monospace'],
    },
  }},
};
