"""The TMC view: run the Fowler scenario in sumo-gui through the same TraCI calls, and save two screenshots.

    python gui_view.py              # on a desktop: a SUMO window opens and closes by itself
    xvfb-run -a -s "-screen 0 1600x900x24" python gui_view.py     # on a server without a screen

Writes tmc_view_network.png (Fowler from McKinley Dr to Leroy Collins Blvd) and tmc_view_30th.png
(Fowler Ave & 30th St / Bruce B Downs).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sumo_agent_tools as T
import traci

T.start_live(gui=True)
v = 'View #0'
traci.gui.setSchema(v, 'real world')
T.advance(1795)
x, y = T._net().getNode(T._resolve('Fowler & 30th')[0]).getCoord()
# The first screenshot of a session can come out with the view misplaced (seen under Xvfb): take a throwaway one.
traci.gui.screenshot(v, os.path.join(HERE, 'runs', 'warmup_shot.png'), 1600, 900)
T.advance(1)
traci.gui.setOffset(v, 1730, 600)                        # Fowler between McKinley Dr and Leroy Collins Blvd
traci.gui.setZoom(v, 320)
T.advance(1)
traci.gui.screenshot(v, os.path.join(HERE, 'tmc_view_network.png'), 1600, 900)
T.advance(1)
traci.gui.setOffset(v, x + 60, y)
traci.gui.setZoom(v, 900)
T.advance(1)
traci.gui.screenshot(v, os.path.join(HERE, 'tmc_view_30th.png'), 1600, 900)
T.advance(2)
print(T.get_corridor_state('WB'))
T.stop_live()
