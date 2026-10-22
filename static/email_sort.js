/* Missing dates always stay at the bottom; polling never resets the chosen order. */
var emailSortField='created_at',emailSortDirection='desc';
function emailSortTime(value){
  if(value===null||value===undefined||value===''||typeof value==='boolean')return null;
  var numeric=typeof value==='number'||/^\d+(\.\d+)?$/.test(String(value));
  var time=numeric?(Number(value)>100000000000?Number(value):Number(value)*1000):Date.parse(value);
  return Number.isFinite(time)&&time>0?time:null;
}
function sortEmailRecords(records){
  var key=emailSortField,direction=emailSortDirection==='desc'?-1:1;
  return records.slice().sort(function(a,b){
    var left=emailSortTime(a[key]),right=emailSortTime(b[key]);
    if(left===null&&right!==null)return 1;
    if(right===null&&left!==null)return -1;
    if(left!==null&&right!==null&&left!==right)return (left-right)*direction;
    return String(a.email||'').localeCompare(String(b.email||''));
  });
}
function toggleEmailSort(key){
  if(key!=='created_at'&&key!=='fastai_synced_at')return;
  if(emailSortField===key)emailSortDirection=emailSortDirection==='desc'?'asc':'desc';
  else{emailSortField=key;emailSortDirection='desc';}
  renderAliasTable();
}
function emailSortHeader(key,label){
  var active=emailSortField===key,order=active?(emailSortDirection==='desc'?'descending':'ascending'):'none';
  var arrow=active?(emailSortDirection==='desc'?' ↓':' ↑'):' ↕';
  var next=active&&emailSortDirection==='desc'?'升序':'倒序';
  return '<th aria-sort="'+order+'"><button type="button" class="email-sort-header" data-email-sort="'+key+'" onclick="toggleEmailSort(\''+key+'\')" title="点击按'+label+next+'排列">'+label+'<span aria-hidden="true">'+arrow+'</span></button></th>';
}
