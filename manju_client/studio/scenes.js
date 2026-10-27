import {T,Builder,materials,resetSeed,rand,between,floor,stairs,column,bracket,lattice,railing,roof,pavilion,chair,vase,lantern,rock,pine,terrain,grass,mountains,medallion} from './geometry.js';
import {SCENES} from './catalog.js';
const groups={};
function hall(b){
 b.begin('青石铺地与中轴纹饰','ground');floor(b,28,48,0,0,0,2);for(let z=-12;z<22;z+=8)medallion(b,0,.085,z,2.8);for(let x of [-3.1,3.1])b.box([x,.085,3],[.09,.025,38],'gold');
 b.begin('两段高台与御道','architecture');
 stairs(b,0,0,-8,14,12,.22,.42);b.box([0,2.54,-15],[16,.18,4.5],'stone');stairs(b,0,2.64,-16,11,11,.23,.42);b.box([0,5.1,-22],[15,.2,4.5],'stone');
 for(let section=0;section<2;section++){let y=section*2.64,z=-10.4-section*7.6;b.box([0,y+1.35,z],[2.2,.15,5.7],'stoneDark',[-.48,0,0]);for(let i=0;i<6;i++)b.ring([0,y+.35+i*.44,z+2-i*.8],.52,.055,'gold',[Math.PI/2-.48,0,0]);for(let x of [-7,7]){railing(b,[x,0,z+2.5],[x,0,z-3],y+.4,'gold',1);}}
 b.begin('青玉柱网与柱脚','architecture');for(let side of [-1,1])for(let z=-20;z<=20;z+=8){column(b,side*9,0,z,14,.63,true);column(b,side*13.3,0,z,14,.4,true);}
 b.begin('双层回廊、栏杆与斗拱','architecture');for(let side of [-1,1]){b.box([side*11.3,7.5,0],[5,.32,46],'woodDark');railing(b,[side*8.9,0,-22],[side*8.9,0,22],7.7,'gold',1.1);for(let z=-20;z<=20;z+=8){for(let y of [7.1,14.3]){bracket(b,side*9,y,z,2.1,true);bracket(b,side*13.3,y,z,1.4,true);b.box([side*11,y+.4,z],[5,.45,.5],'wood');}for(let x of [side*9.15,side*12.8]){b.box([x,7.2,z+4],[.28,.35,8],'gold');}}}
 b.begin('格栅长窗与侧墙','walls');for(let side of [-1,1]){for(let z=-20;z<=20;z+=4){lattice(b,side*14,4,z,3.1,6.8,side*Math.PI/2);lattice(b,side*14,11.4,z,3.1,5,side*Math.PI/2);}b.box([side*14,7.5,0],[.3,1.1,48],'woodDark');}
 b.begin('藻井与梁架','roof');b.box([0,16.1,0],[28,.3,48],'woodDark');for(let xx=-12;xx<=12;xx+=3)for(let zz=-22;zz<23;zz+=4){b.box([xx,15.93,zz],[2.3,.04,3.3],'wood');for(let zedge of [-1.7,1.7])b.box([xx,15.85,zz+zedge],[2.5,.06,.06],'gold');for(let xedge of [-1.25,1.25])b.box([xx+xedge,15.85,zz],[.06,.06,3.4],'gold');}for(let z=-22;z<=22;z+=4){b.box([0,15.2,z],[28,.65,.5],'woodDark');for(let x=-12;x<=12;x+=3)b.box([x,15.6,z],[.25,.3,4.2],'gold');}for(let x=-12;x<=12;x+=3)b.box([x,15.7,0],[.28,.35,48],'wood');for(let i=0;i<4;i++){let s=8-i*1.3;for(let z of [-s/2,s/2])b.box([0,16.2+i*.18,z],[s,.18,.16],'gold');for(let x of [-s/2,s/2])b.box([x,16.2+i*.18,0],[.16,.18,s],'gold');}
 b.begin('山海照壁与主座','furniture');b.box([0,10,-24],[17,11,.4],'woodDark');b.box([0,10,-23.76],[12.6,9.4,.06],'grandMural');for(let x of [-6.45,6.45])b.box([x,10,-23.6],[.18,10,.2],'gold');for(let y of [5.2,14.8])b.box([0,y,-23.6],[13,.18,.2],'gold');chair(b,0,5.3,-21.4,2.5,0,true);for(let x of [-2.8,2.8]){b.box([x,5.85,-21.2],[1,.9,1],'woodDark');vase(b,x,6.35,-21.2,1.4);}
 b.begin('两翼礼器与香案','furniture');for(let side of [-1,1])for(let z=-19;z<20;z+=5){let x=side*11.2;let y=z< -10?1.4:0;b.box([x,y+.8,z],[2.3,1.6,2],'woodDark');for(let yy of [y+.1,y+1.5])b.box([x,yy,z],[2.4,.1,2.1],'gold');vase(b,x,y+1.65,z,1.7);for(let dx of [-.8,.8]){b.cyl([x+dx,y+2,z+.65],.055,.8,'gold');b.cyl([x+dx,y+2.5,z+.65],.09,.22,'cream');}railing(b,[side*7.6,0,z-2],[side*7.6,0,z+2],y,'gold',.8);}
 b.begin('反打入口与门扉','walls');for(let x of [-10.5,10.5]){b.box([x,7,24],[7,14,.55],'woodDark');lattice(b,x,6.5,23.65,5,10);}b.box([0,12.6,24],[14,3,.6],'wood');for(let x of [-7,7])column(b,x,0,23.5,12,.45,true);b.box([0,10.8,23.6],[14,.5,.8],'gold');
}
function residence(b){
 b.begin('青石地面','ground');floor(b,22,29,0,0,0,1.8);
 b.begin('木柱与横梁','architecture');for(let side of [-1,1])for(let z=-12;z<=12;z+=6){column(b,side*8.4,0,z,8.4,.32);bracket(b,side*8.4,8.6,z,1.5);b.box([0,9,z],[21,.45,.42],'woodDark');}for(let x of [-8.4,8.4])b.box([x,8.5,0],[.35,.45,28],'wood');
 b.begin('白墙与山水画照壁','walls');b.box([0,4.8,-14.5],[22,9.6,.3],'plaster');b.box([0,5.55,-14.24],[13.4,7.9,.18],'woodDark');b.box([0,5.55,-14.13],[12.9,7.4,.04],'mural');for(let x of [-6.65,6.65])b.box([x,5.55,-14.08],[.12,7.9,.1],'gold');
 b.begin('两侧高窗','walls');for(let side of [-1,1])for(let z=-10.5;z<14;z+=3.8){b.box([side*11,1,z],[.24,2,3.8],'plaster');lattice(b,side*10.96,5.3,z,3.4,6.3,side*Math.PI/2);}
 b.begin('屋顶梁架','roof');b.box([0,9.95,0],[22,.2,29],'woodDark');for(let z=-14;z<15;z+=.5)b.box([0,9.4,z],[22,.14,.12],'wood');for(let x=-9;x<=9;x+=3)b.box([x,9.7,0],[.35,.35,29],'woodDark');
 b.begin('主座与茶案','furniture');b.box([0,.24,-11.8],[6.3,.48,3.4],'wood');stairs(b,0,0,-9.8,2.6,2,.17,.35,'wood');chair(b,0,.5,-12,1.9,0,true);for(let x of [-2,2]){b.box([x,1,-12],[.65,1,.65],'woodDark');vase(b,x,1.5,-12,.8);}for(let x of [-5.2,5.2]){b.box([x,.85,-13.4],[3.7,.15,.7],'wood');for(let dx of [-1.65,1.65])b.box([x+dx,.4,-13.4],[.07,.8,.5],'wood');for(let dx of [-.8,0,.8])vase(b,x+dx,.94,-13.4,.5);}
 for(let side of [-1,1]){b.begin(side<0?'左列座椅 · 14 把':'右列座椅 · 14 把','furniture');for(let i=0;i<7;i++)for(let j=0;j<2;j++)chair(b,side*(4.2+j*1.6),0,-7.5+i*2.2,1,side*Math.PI/2);}
 b.begin('室内树池与古松','nature');for(let x of [-9.4,9.4])for(let z of [-6,7]){b.box([x,.25,z],[2.4,.5,5.2],'woodDark');pine(b,x,.5,z,.9, x<0?.5:-.5);}
 b.begin('入口框架','walls');for(let x of [-7.5,7.5]){b.box([x,2.2,14],[7,4.4,.3],'plaster');lattice(b,x,5.7,14,6,2);}b.box([0,7.5,14],[22,.5,.6],'wood');
}
function gate(b){
 b.begin('门前石坪与台阶','ground');floor(b,54,35,0,0,10,2);b.box([0,1.1,-3],[44,2.2,14],'stone');stairs(b,0,0,6.5,14,9,.24,.48);for(let side of [-1,1])stairs(b,side*19,0,7,4.2,10,.22,.43);
 b.begin('门楼柱网与门洞','architecture');for(let side of [-1,1])for(let z of [-5.5,.5]){column(b,side*5.2,2.2,z,5.2,.4);bracket(b,side*5.2,7.6,z,1.7);}for(let side of [-1,1]){b.box([side*4,4.7,-2.5],[2.2,5,6.2],'plaster');}b.box([0,7.4,-2.5],[12,.65,7],'woodDark');for(let x=-5.2;x<=5.2;x+=2.6)bracket(b,x,7.7,1,1.3);b.box([0,7,-.2],[7,.45,.45],'wood');
 b.begin('重檐青瓦与脊饰','roof');roof(b,0,8,-2.5,17,10.5,2);b.box([0,9.9,-2.5],[9.5,1.6,5],'plaster');for(let x=-4.5;x<=4.5;x+=1.5)bracket(b,x,11,-.1,.8);roof(b,0,11,-2.5,12.5,7.3,1.7);
 for(let side of [-1,1]){b.begin(side<0?'左门扇':'右门扇','furniture');const x=side*2.6;const p=b.part;p.position.set(x,2.3,.2);p.rotation.y=side*1.03;b.box([-side*1.25,2.2,0],[2.5,4.4,.16],'wood');for(let xx=0;xx<5;xx++)b.box([-side*(.25+xx*.5),2.2,.1],[.035,4.2,.035],'gold');for(let yy of [.4,1.7,3.7])b.box([-side*1.25,yy,.15],[2.45,.13,.12],'woodDark');b.ring([-side*2,1.9,.23],.14,.035,'gold',[0,0,0]);}
 b.begin('左右白墙及压顶','walls');for(let side of [-1,1]){b.box([side*14,4,-2.5],[17,3.6,.65],'plaster');b.box([side*14,2.5,-2.5],[17,.6,.8],'stone');roof(b,side*14,5.8,-2.5,18,1.8,.6);for(let x=6.5;x<22;x+=2.5)bracket(b,side*x,5.65,-2.1,.55);}
 b.begin('两翼亭廊','architecture');for(let side of [-1,1]){pavilion(b,side*21,3.2,-9,9,8,5,1);railing(b,[side*7,0,4.5],[side*17,0,4.5],2.2);lantern(b,side*8.4,2.2,4.3,1.2);}
 b.begin('门后庭院 · 推定','architecture');floor(b,30,21,2.2,0,-20,2);pavilion(b,0,2.2,-24,15,8,5,1);
 b.begin('前景古松与山石','nature');for(let side of [-1,1]){pine(b,side*20,0,10,2.2,-side*.8);for(let i=0;i<9;i++)rock(b,[side*between(18,26),between(.2,2),between(-3,18)],[between(.6,2.5),between(.8,3),between(.6,2)],'rock');}b.begin('远山','landscape');mountains(b,73,-15);
}
function arena(b){
 b.begin('广场铺地与轴线','ground');floor(b,80,94,0,0,0,3.2);for(let x of [-1.2,1.2])b.box([x,.1,0],[.1,.04,92],'gold');for(let z of [-20,22])for(let x of [-27,27])medallion(b,x,.12,z,3);
 b.begin('圆形演武擂台','architecture');b.cyl([0,1.2,8],14,2.4,'stoneDark',14,128);b.cyl([0,2.42,8],14.25,.22,'stone',14.25,128);medallion(b,0,2.55,8,4.3);for(let r of [7,11.5,13.7])b.ring([0,2.55,8],r,.045,'gold');for(let i=0;i<16;i++){let a=i*Math.PI/8;b.beam([Math.cos(a)*4.5,2.55,8+Math.sin(a)*4.5],[Math.cos(a)*13.7,2.55,8+Math.sin(a)*13.7],.035,'stoneDark');}
 for(let angle of [0,Math.PI/2,Math.PI,Math.PI*1.5]){const t=new Builder(b.mats);t.begin('stairs');stairs(t,0,0,18.5,7,10,.24,.46);t.done();t.part.children.forEach(m=>{b.add(m.geometry,m.material.name,[0,0,8],[1,1,1],[0,angle,0]);m.geometry.dispose();});}
 for(let i=0;i<32;i++){let a=i*Math.PI/16;if(Math.abs(Math.sin(a*2))<.38)continue;let x=14*Math.cos(a),z=8+14*Math.sin(a);b.box([x,1.25,z],[.35,2,.35],'gold',[0,-a,0]);}
 b.begin('中轴多级台基与御阶','architecture');for(let k=0;k<3;k++){let z=-22-k*12,y=k*2.4;b.box([0,y+1.2,z],[42-7*k,2.4,11],'stone');stairs(b,0,y,z+9.4,12-2*k,10,.24,.42);for(let side of [-1,1])railing(b,[side*8,0,z+5],[side*(20-3.5*k),0,z+5],y+2.4);}
 for(let side of [-1,1]){b.begin(side<0?'左翼殿宇群':'右翼殿宇群','architecture');pavilion(b,side*28,1,5,14,10,5.6,2);pavilion(b,side*27,2.2,-19,12,8,4.6,1);pavilion(b,side*24,4.5,-35,10,8,5,2);pavilion(b,side*31,0,34,7,6,3.8,1);}
 b.begin('中轴主殿与山门','architecture');pavilion(b,0,7.2,-48,21,12,7.5,3);for(let x of [-7,7])column(b,x,4.8,-31,6,.35,true);b.box([0,11.1,-31],[17,.6,1],'gold');roof(b,0,11.6,-31,18,3,1.3);
 b.begin('石栏与灯座','architecture');for(let side of [-1,1]){railing(b,[side*39,0,-42],[side*39,0,44],0,'stone',1.3);for(let z=-38;z<=42;z+=10){lantern(b,side*20,0,z,1.25);lantern(b,side*37,0,z,1.1);}}
 b.begin('广场园林','nature');for(let side of [-1,1])for(let i=0;i<13;i++){let x=side*between(33,46),z=between(-45,45);pine(b,x,0,z,between(.9,1.7),between(-.3,.3),i<6);rock(b,[x+1,1,z],[2,2.3,1.8]);}b.begin('群山','landscape');mountains(b,100,-15);
}
function summit(b){
 const h=(x,z)=>1.6*Math.sin(z*.09)+.65*Math.cos(x*.25)+.4*Math.sin(x*.7+z*.17);const width=z=>z< -15?20:14+5*Math.sin(z*.05);
 b.begin('连续崖顶草甸','ground');terrain(b,36,94,(x,z)=>h(x,z),0,0,'grass',100);grass(b,14000,34,90,h);
 b.begin('断崖岩体与石脊','landscape');for(let z=-45;z<48;z+=5.3)for(let side of [-1,1]){let x=side*(17+Math.sin(z*.15)*1.5);rock(b,[x,-15,z],[between(3,6),between(14,20),between(4,7)],'rock',3);rock(b,[x*.9,h(x,z)-.4,z],[between(2,4),1.7,between(2,4)],'moss');}
 b.begin('峰顶殿宇','architecture');b.box([1,1.6,-33],[31,2.3,28],'stone');pavilion(b,7,2.8,-36,16,12,6,3);pavilion(b,-8,2.8,-27,9,7,4,1);pavilion(b,9,2.8,-22,8,6,3.5,1);railing(b,[-14,0,-19],[15,0,-19],2.8);stairs(b,-4,0,-15,5,12,.23,.35);
 b.begin('云端牌坊','architecture');for(let x of [-11,-3])column(b,x,2.8,-40,12,.47);for(let yy of [10.4,13.5]){b.box([-7,yy,-40],[12,.5,1],'stone');roof(b,-7,yy+.3,-40,13,3.3,1.1);}
 b.begin('崖顶松树','nature');for(let i=0;i<16;i++){let x=between(-16,16),z=between(-10,45);if(Math.abs(x)<8)continue;pine(b,x,h(x,z),z,between(.6,1.2),.2,i<8);}b.begin('云海远峰','landscape');mountains(b,90,-32);
}
function valley(b,path=false){
 const h=(x,z)=>path?Math.max(0,(20-z)*.18)+.12*Math.sin(x*.8):.18*Math.sin(x*.45)*Math.cos(z*.22);
 b.begin(path?'贴崖山道基体':'山谷地形','ground');if(!path)terrain(b,42,65,h,0,-4,'earth',90);else pathBase(b);
 b.begin(path?'曲折上升石阶':'不规则石层道路','ground');
 if(path){for(let i=0;i<48;i++){let z=25-i*1.22,x=2+8*Math.sin(i*.035);let y=i*.23;for(let j=0;j<4;j++){b.box([x-3.2+j*2.05+between(-.12,.12),y-.16,z],[2.1,.42+between(-.06,.06),1.3],rand()<.2?'stoneDark':'stone',[between(-.01,.01),between(-.025,.025),0]);}for(let k=0;k<3;k++)rock(b,[x-4.6,y-.1,z+between(-.5,.5)],[.6,.35,.65],'rock',1);}
 for(let i=23;i<47;i++){let z=25-i*1.22,x=2+8*Math.sin(i*.035)+4.1,y=i*.23;b.beam([x,y,z],[x,y+1.1,z],.075,'wood');if(i>23){let z0=z+1.22,x0=2+8*Math.sin((i-1)*.035)+4.1;for(let yy of [.45,1])b.beam([x,y+yy,z],[x0,y-.23+yy,z0],.055,'wood');}}
 }else{for(let i=0;i<130;i++){let x=between(-9,9),z=between(-33,28),y=h(x,z);rock(b,[x,y-.12,z],[between(.7,2.2),between(.15,.35),between(.4,1.4)],'earth',1);}grass(b,1800,7,62,h,-13,-4);grass(b,1800,7,62,h,13,-4);}
 b.begin('左侧层叠崖壁','landscape');for(let i=0;i<18;i++){let z=26-i*4,x=path?-13:-17;for(let j=0;j<3;j++)rock(b,[x+between(-3,2),j*8+3+h(x,z),z],[between(4,7),between(5,9),between(3,5)],'rock',3);}
 b.begin(path?'右侧悬崖与峰柱':'右侧山坡岩体','landscape');for(let i=0;i<13;i++){let z=22-i*5,x=path?17:19;rock(b,[x+between(-2,4),path?-9:between(1,5),z],[between(5,8),path?between(9,17):between(3,7),between(4,6)],'rock',3);}if(path)for(let i=0;i<5;i++)rock(b,[between(-33,-23),-5,between(-40,-10)],[5,between(15,29),5],'rock',3);
 b.begin('近景横生古松','nature');pine(b,path?11:13,path?4:0,16,path?2.6:2.4,-1.7,true);pine(b,-12,path?3:0,7,2.1,1.1,true);
 b.begin('崖壁植被与散石','nature');for(let i=0;i<30;i++){let side=i%2?1:-1,x=side*between(path?12:11,path?19:24),z=between(-37,24),y=path?Math.max(1,h(x,z)+between(-4,3)):h(x,z);pine(b,x,y,z,between(.55,1.4),side*-.5,i<10);rock(b,[x*.83,y-.25,z],[between(.5,1.7),between(.4,1.3),between(.5,1.5)],'moss',1);}
 b.begin('层叠远山','landscape');mountains(b,76,-12);
}
export function buildScene(id){const index=SCENES.findIndex(s=>s.id===id);if(index<0)throw Error('Unknown scene');resetSeed(1001+index*919);const mats=materials(),b=new Builder(mats);b.root.name=SCENES[index].name;({ 'grand-hall':hall,'summit':summit,'residence-hall':residence,'residence-gate':gate,'rescue':b=>valley(b,false),'arena':arena,'mountain-path':b=>valley(b,true)})[id](b);const root=b.done();root.userData={...root.userData,sceneId:id,version:'1.0',referenceFiles:SCENES[index].refs.map(n=>n+'.png'),inferred:SCENES[index].inference,units:'meters-estimated',review:'pending'};return {root,mats,meta:SCENES[index]};}

function pathBase(b){const positions=[],uv=[],idx=[];const rows=49;for(let i=0;i<rows;i++){let z=25-i*1.22,x=2+8*Math.sin(i*.035),y=i*.23-.44;for(let [xx,yy] of [[x-4.5,-22],[x-4.5,y],[x+4.5,y],[x+4.5,-22]]){positions.push(xx,yy,z);uv.push((xx+20)*.18,(z+yy)*.12);}}for(let i=0;i<rows-1;i++)for(let k=0;k<3;k++){let a=i*4+k;idx.push(a,a+1,a+4,a+1,a+5,a+4);}const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(positions,3));g.setAttribute('uv',new T.Float32BufferAttribute(uv,2));g.setIndex(idx);g.computeVertexNormals();b.add(g,'rock');g.dispose();}
