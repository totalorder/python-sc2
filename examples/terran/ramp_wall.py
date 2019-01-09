import random
import logging
logger = logging.getLogger(__name__)

import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer
from sc2.position import Point2, Point3


class RampWallBot(sc2.BotAI):
    async def on_step(self, iteration):
        cc = self.units(COMMANDCENTER)
        if not cc.exists:
            return
        else:
            cc = cc.first

        if self.can_afford(SCV) and self.workers.amount < 16 and cc.noqueue:
            await self.do(cc.train(SCV))


        # Raise depos when enemies are nearby
        for depo in self.units(SUPPLYDEPOT).ready:
            for unit in self.known_enemy_units.not_structure:
                if unit.position.to2.distance_to(depo.position.to2) < 15:
                    break
            else:
                await self.do(depo(MORPH_SUPPLYDEPOT_LOWER))

        # Lower depos when no enemies are nearby
        for depo in self.units(SUPPLYDEPOTLOWERED).ready:
            for unit in self.known_enemy_units.not_structure:
                if unit.position.to2.distance_to(depo.position.to2) < 10:
                    await self.do(depo(MORPH_SUPPLYDEPOT_RAISE))
                    break

        depot_placement_positions = self.main_base_ramp.corner_depots
        # Uncomment the following if you want to build 3 supplydepots in the wall instead of a barracks in the middle + 2 depots in the corner
        # depot_placement_positions = self.main_base_ramp.corner_depots | {self.main_base_ramp.depot_in_middle}

        barracks_placement_position = None
        barracks_placement_position = self.main_base_ramp.barracks_correct_placement
        # If you prefer to have the barracks in the middle without room for addons, use the following instead
        # barracks_placement_position = self.main_base_ramp.barracks_in_middle

        depots = self.units(SUPPLYDEPOT) | self.units(SUPPLYDEPOTLOWERED)

        # Filter locations close to finished supply depots
        if depots:
            depot_placement_positions = {d for d in depot_placement_positions if depots.closest_distance_to(d) > 1}

        # Build depots
        if self.can_afford(SUPPLYDEPOT) and not self.already_pending(SUPPLYDEPOT):
            if len(depot_placement_positions) > 0:
                # Choose any depot location
                target_depot_location = depot_placement_positions.pop()
                gathering = self.workers.gathering
                if gathering: # if workers were found
                    w = gathering.random
                    await self.do(w.build(SUPPLYDEPOT, target_depot_location))

        # Build barracks
        if depots.ready.exists and self.can_afford(BARRACKS) and not self.already_pending(BARRACKS):
            if self.units(BARRACKS).amount + self.already_pending(BARRACKS) == 0:
                gathering = self.workers.gathering
                if gathering and barracks_placement_position:
                    w = gathering.random
                    await self.do(w.build(BARRACKS, barracks_placement_position))

        # Build refinery after barracks
        if (self.already_pending(BARRACKS) or self.units(BARRACKS).amount) \
                and not self.units(REFINERY).exists and not self.already_pending(REFINERY) \
            and self.can_afford(REFINERY):
                vgs = self.state.vespene_geyser.closer_than(20.0, cc)
                for vg in vgs:
                    if self.units(REFINERY).closer_than(1.0, vg).exists:
                        break

                    worker = self.select_build_worker(vg.position)
                    if worker is None:
                        break

                    await self.do(worker.build(REFINERY, vg))
                    break

        # Assign workers to refinery
        for refinery in self.units(REFINERY):
            if refinery.assigned_harvesters < refinery.ideal_harvesters:
                w = self.workers.closer_than(20, refinery)
                if w.exists:
                    await self.do(w.random.gather(refinery))

        # Build reactor
        for barracks in self.units(BARRACKS).ready:
            if barracks.add_on_tag == 0 and self.can_afford(BARRACKSREACTOR) and \
                    not self.units(BARRACKSREACTOR).not_ready.exists:
                await self.do(barracks.build(BARRACKSREACTOR))
                continue

            # TODO: Check build queue
            if self.can_afford(MARINE) and self.supply_left > 0:
                await self.do(barracks.train(MARINE))

        # Assign idle workers to minerals
        for scv in self.units(SCV).idle:
            await self.do(scv.gather(self.state.mineral_field.closest_to(cc)))

        # Attack in squads of 12 marines
        idle_marines = self.units(MARINE).idle
        if idle_marines.amount >= 12:
            for marine in idle_marines:
                await self.do(marine.attack(self.enemy_start_locations[0]))

        # Repair supply depot
        for depot in self.units(SUPPLYDEPOT).ready:
            # TODO: Don't send all workers
            if depot.health_percentage < 1 and not depot.is_repairing:
                gathering = self.workers.gathering
                if gathering:
                    await self.do(gathering.random.repair(depot))


def main():
    sc2.run_game(sc2.maps.get("OdysseyLE"), [
        Bot(Race.Terran, RampWallBot()),
        Computer(Race.Zerg, Difficulty.Hard)
    ], realtime=False)

if __name__ == '__main__':
    main()
