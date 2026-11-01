"""Small fixed math/range regression; never opens saved experiment data."""
import json
import numpy as np
from diagnose import transform, stream_rows, loaded_points, summarize


def main():
    pose=[1.,2.,3.,2.,0.,0.,0.]
    np.testing.assert_array_equal(transform(pose),[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]])
    data={'normal_indices':np.array([2,3]),'normal_counts':np.array([[1,1]]),'normal_starts':np.array([[2,3]]),
          'friction_indices':np.array([7]),'friction_counts':np.array([[0,1]]),'friction_starts':np.array([[-1,7]]),
          'normal_forces_N':np.array([[2.],[-3.]]),'normal_vectors_world':np.array([[0,1,0],[0,1,0]]),
          'normal_points_world_m':np.array([[1,2,3.05],[1,2,3.06]]),'normal_separations_m':np.array([[0.],[0.]]),
          'friction_forces_world_N':np.array([[0,0,.4]]),'normal_impulses_Ns':np.array([[.02],[-.03]]),
          'friction_impulses_world_Ns':np.array([[0,0,.004]]),
          'filtered_normal_impulse_matrix_world_Ns':np.array([[[0,.02,0],[0,-.03,0]]]),
          'all_body_net_normal_impulse_world_Ns':np.array([[0,-.01,0]])}
    assert [r.tolist() for r in stream_rows(data,'normal',16)]==[[0],[1]]
    assert [r.tolist() for r in stream_rows(data,'friction',16)]==[[],[0]]
    view={'filter_paths':[['a','b']],'max_contact_data_count':16}
    summary=summarize(data,view,.01)
    assert all(summary['checks'].values())
    assert summary['pairs']['a']['raw_friction_world_Z_sum_N']==0
    assert summary['pairs']['b']['raw_friction_world_Z_sum_N']==.4
    assert summary['pairs']['b']['normal_sumabs_N']==3
    points=loaded_points(data,[0,1],pose,'left',{'inner_plane_y_m':0.},.061,1e-8)
    assert points[0]['flat_and_normal_compatible'] is True
    assert points[1]['flat_and_normal_compatible'] is False
    np.testing.assert_allclose([p['local_Z_to_authored_tip_m'] for p in points],[.011,.001],atol=1e-15)
    json.dumps({'points':points,'summary':summary},allow_nan=False)
    corrupt=dict(data,friction_indices=np.array([6]))
    try: stream_rows(corrupt,'friction',16)
    except ValueError: pass
    else: raise AssertionError('Wrong friction compact mapping accepted')
    print('PASS: normalized poses, separate streams, signs, local tip distances, range rejection and strict JSON')


if __name__=='__main__': main()
