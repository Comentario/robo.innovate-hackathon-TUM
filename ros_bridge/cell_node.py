"""Waypoint visualization of an execution contract; not a robot or physics simulator."""
import json
from geometry_msgs.msg import Point
from visualization_msgs.msg import Marker, MarkerArray
from execution import compile_job, ExecutionSession, SimulatedAdapter
from execution.cell import CellLayout, pose
from .nodes import PreviewNode


class CellExecutionNode(PreviewNode):
    def __init__(self, cell_config, prefix='/munich_demo', period=.3, fail_step=None, fail_phase='pick', unknown=False):
        self.cell = CellLayout(cell_config)
        if self.cell.frame != 'world':
            raise ValueError('ROS cell preview requires an explicit world-frame layout')
        self.session = None
        self.inventory = []
        self.trace = []
        self.fail_phase,self.unknown = fail_phase,unknown
        super().__init__(prefix,period,fail_step)

    def on_plan(self, message):
        self.session,self.inventory,self.trace = None,[],[]
        self.marker_publisher.publish(MarkerArray(markers=[self.clear_marker()]))
        try:
            response = json.loads(message.data)
            if response.get('schema_version') != 'ros-envelope-0.1' or response.get('status') != 'planned':
                raise ValueError(response.get('reason','plan response rejected'))
            self.inventory = response['source_inventory']
            job = compile_job(response['plan'],self.inventory,self.cell.config)
            if self.fail_step is not None and not 1 <= self.fail_step <= len(job['plan']['placements']):
                raise ValueError('fail_step must identify a placement')
            self.session = ExecutionSession(job,SimulatedAdapter(self.fail_step,self.fail_phase,self.unknown))
            self.event('ready',confirmed=0,preview='synthetic_cell_waypoints')
            self.draw()
        except (ValueError,KeyError,TypeError,AttributeError) as error:
            self.session = None
            self.event('rejected',reason=str(error))

    def clear_marker(self):
        marker=Marker()
        marker.header.frame_id='world'
        marker.action=Marker.DELETEALL
        return marker

    def cube(self,namespace,index,value,size,color):
        marker=Marker()
        marker.header.frame_id='world'
        marker.ns,marker.id,marker.type,marker.action=namespace,index,Marker.CUBE,Marker.ADD
        marker.pose.position.x,marker.pose.position.y,marker.pose.position.z=value['position_m']
        marker.pose.orientation.x,marker.pose.orientation.y,marker.pose.orientation.z,marker.pose.orientation.w=value['orientation_xyzw']
        marker.scale.x,marker.scale.y,marker.scale.z=size
        marker.color.r,marker.color.g,marker.color.b,marker.color.a=color
        return marker

    def draw(self):
        if self.session is None:return
        session=self.session
        job=session.job
        palette=dict(dark=(.44,.26,.19,1.),medium=(.72,.47,.32,1.),light=(.91,.78,.63,1.))
        markers=[self.clear_marker()]
        for i,brick in enumerate(self.inventory):
            if brick['id'] not in session.available:continue
            group=brick.get('color_group') or ((brick.get('faces') or {}).get('front') or {}).get('color_group','unknown')
            markers.append(self.cube('source',i,job['source_poses'][brick['id']],self.cell.size,palette.get(group,(.5,.5,.5,1.))))
        by_id={p['brick_id']:p for p in job['plan']['placements']}
        for p in session.confirmed:
            markers.append(self.cube('bricks',p['step'],self.cell.target_pose(p),self.cell.size,palette.get(p['color_group'],(.5,.5,.5,1.))))
        if session.placed_unconfirmed:
            p=by_id[session.placed_unconfirmed]
            markers.append(self.cube('unconfirmed',0,self.cell.target_pose(p),self.cell.size,(1.,.35,.1,1.)))
        if session.held_brick:
            p=by_id[session.held_brick]
            markers.append(self.cube('held',0,session.object_pose,self.cell.size,palette.get(p['color_group'],(.5,.5,.5,1.))))
        tool=self.cube('tool',0,session.object_pose,(.06,.06,.06),(1.,.2,.2,1.) if session.status=='stopped' else (.2,.9,.9,1.))
        tool.type=Marker.SPHERE
        tool.pose.position.z+=.09
        markers.append(tool)
        # Work surfaces are simple rectangles under synthetic brick grids.
        origins=list(job['source_poses'].values())
        source_x=[p['position_m'][0] for p in origins]
        source_y=[p['position_m'][1] for p in origins]
        source_size=(max(source_x)-min(source_x)+self.cell.size[0]+.06,max(source_y)-min(source_y)+self.cell.size[1]+.06,.035)
        source_center=[(min(source_x)+max(source_x))/2,(min(source_y)+max(source_y))/2,self.cell.source[2]-self.cell.size[2]/2-.0175]
        markers.append(self.cube('cell',0,pose(source_center),source_size,(.20,.29,.34,1.)))
        capacity=self.cell.capacity
        target_size=((capacity['columns']-1)*self.cell.target_pitch[0]+self.cell.size[0]+.06,
                     (capacity['rows']-1)*self.cell.target_pitch[1]+self.cell.size[1]+.06,.035)
        target_center=[self.cell.target[0]+(capacity['columns']-1)*self.cell.target_pitch[0]/2,
                       self.cell.target[1]+(capacity['rows']-1)*self.cell.target_pitch[1]/2,
                       self.cell.target[2]-self.cell.size[2]/2-.0175]
        markers.append(self.cube('cell',1,pose(target_center),target_size,(.35,.30,.22,1.)))
        path=Marker()
        path.header.frame_id='world'
        path.ns,path.id,path.type,path.action='waypoints',0,Marker.LINE_STRIP,Marker.ADD
        path.pose.orientation.w=1.
        path.scale.x=.004
        path.color.r,path.color.g,path.color.b,path.color.a=.2,.8,.8,.7
        path.points=[Point(x=p[0],y=p[1],z=p[2]+.09) for p in self.trace]
        if len(path.points)>=2:markers.append(path)
        self.marker_publisher.publish(MarkerArray(markers=markers))

    def tick(self):
        if self.session is None or self.session.status in ('completed','stopped'):return
        event=self.session.advance()
        if event['outcome']=='succeeded':
            self.trace.append(self.session.object_pose['position_m'][:])
        self.draw()
        fields={k:v for k,v in event.items() if k not in ('status','execution')}
        fields.update(held_brick=self.session.held_brick,placed_unconfirmed=self.session.placed_unconfirmed,
                      uncertain_brick=self.session.uncertain_brick,preview='synthetic_cell_waypoints')
        self.event(event['status'],**fields)
