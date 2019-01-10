import random
import logging

from sc2.units import Units

logger = logging.getLogger(__name__)

import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer
from sc2.position import Point2, Point3
from examples.zerg import zerg_rush

class RampWallBot(sc2.BotAI):
    def should_build(self, unit_type_id: UnitTypeId) -> bool:
        return self.can_afford(unit_type_id) and \
               (not self.already_pending(unit_type_id) or self.minerals > 500)

    async def on_step(self, iteration):
        cc = self.units(COMMANDCENTER)
        if not cc.exists:
            return
        else:
            cc = cc.first

        if self.can_afford(SCV) and self.workers.amount < 16 and cc.noqueue:
            await self.do(cc.train(SCV))

        depot_placement_positions = self.main_base_ramp.corner_depots
        # Uncomment the following if you want to build 3 supplydepots in the wall instead of a barracks in the middle + 2 depots in the corner
        # depot_placement_positions = self.main_base_ramp.corner_depots | {self.main_base_ramp.depot_in_middle}

        barracks_placement_position = None
        barracks_placement_position = self.main_base_ramp.barracks_correct_placement
        # If you prefer to have the barracks in the middle without room for addons, use the following instead
        # barracks_placement_position = self.main_base_ramp.barracks_in_middle

        all_depots = self.units(SUPPLYDEPOT) | self.units(SUPPLYDEPOTLOWERED)

        # Filter locations close to finished supply depots
        wall_depots = None
        if all_depots:
            wall_depots = Units(list(depot for depot in all_depots if min(depot.distance_to(d) for d in depot_placement_positions) <= 1), self.game_info)
            depot_placement_positions = {d for d in depot_placement_positions if all_depots.closest_distance_to(d) > 1}
        if iteration % 10 == 0:
            logger.info(f"wall_depots: {wall_depots}, depot_placement_positions: {depot_placement_positions}")
        # Build 2 depots for wall
        if self.can_afford(SUPPLYDEPOT) and not self.already_pending(SUPPLYDEPOT):
            if len(depot_placement_positions) > 0:
                # Choose any depot location
                target_depot_location = depot_placement_positions.pop()
                gathering = self.workers.gathering
                if gathering: # if workers were found
                    w = gathering.random
                    await self.do(w.build(SUPPLYDEPOT, target_depot_location))

        # Build barracks for wall
        if all_depots.ready.exists and self.should_build(BARRACKS):
            if not self.units(BARRACKS).exists:
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

        # Build more supply depots
        if self.supply_left <= 6:
            if self.should_build(SUPPLYDEPOT):
                await self.build(SUPPLYDEPOT, near=cc.position.towards(self.game_info.map_center, 8))

        # Build reactors
        for barracks in self.units(BARRACKS).ready:
            reactor = [reactor for reactor in self.units(BARRACKSREACTOR)
                       if reactor.add_on_land_position == barracks.position]
            if reactor:
                reactor = reactor[0]

            if not reactor and self.can_afford(BARRACKSREACTOR):
                await self.do(barracks.build(BARRACKSREACTOR))

            # Build marines
            elif self.can_afford(MARINE) and self.supply_left > 0 and \
                    len(barracks.orders) < 2 and reactor.is_ready:
                await self.do(barracks.train(MARINE))

        # Build more barracks after the first is done
        if self.units(BARRACKS).ready.exists and self.should_build(BARRACKS):
            await self.build(BARRACKS, near=cc.position.towards(self.game_info.map_center, 8))

        # Assign idle workers to minerals
        for scv in self.units(SCV).idle:
            await self.do(scv.gather(self.state.mineral_field.closest_to(cc)))

        if barracks_placement_position and iteration % 50 == 0:
            marines_at_wall = self.units(MARINE).closer_than(20, barracks_placement_position)

            # Attack when 12 are at the wall
            if marines_at_wall.amount >= 12:
                for marine in marines_at_wall:
                    await self.do(marine.attack(self.enemy_start_locations[0]))

            # Move idle marines to wall
            elif wall_depots:
                idle_marines = self.units(MARINE).idle
                for marine in idle_marines:
                    if wall_depots.closest_distance_to(marine) > 3:
                        await self.do(marine.move(wall_depots.random))

        # Lower depot when no enemies are nearby or we have a defending force
        for depot in self.units(SUPPLYDEPOT).ready:
            if self.units(MARINE).closer_than(6, depot).amount >= 8:
                await self.do(depot(MORPH_SUPPLYDEPOT_LOWER))
                continue

            for unit in self.known_enemy_units.not_structure:
                if unit.position.to2.distance_to(depot.position.to2) < 15:
                    break
            else:
                await self.do(depot(MORPH_SUPPLYDEPOT_LOWER))

        # Raise depot when enemies are nearby unless we have a defending force
        for depot in self.units(SUPPLYDEPOTLOWERED).ready:
            if self.units(MARINE).closer_than(6, depot).amount >= 8:
                continue

            for unit in self.known_enemy_units.not_structure:
                if unit.position.to2.distance_to(depot.position.to2) < 10:
                    await self.do(depot(MORPH_SUPPLYDEPOT_RAISE))
                    break

        # List all buildings in need of repairs
        repairs_needed = [building for building in self.units(SUPPLYDEPOT).ready |
                          self.units(SUPPLYDEPOTLOWERED).ready |
                          self.units(BARRACKS).ready
                          if building.health_percentage < 1]

        # Send on average 3 SCVs to each building in need of repairs
        repairers_active = len([scv for scv in self.workers if scv.is_repairing])
        for index in range(0, max(0, len(repairs_needed) * 3 - repairers_active)):
            target = repairs_needed[index % len(repairs_needed)]
            gathering = self.workers.gathering.closest_to(target)
            if gathering:
                await self.do(gathering.repair(target))

def main():
    sc2.run_game(sc2.maps.get("OdysseyLE"), [
        Bot(Race.Terran, RampWallBot()),
        Bot(Race.Zerg, zerg_rush.ZergRushBot())
    ], realtime=False)

if __name__ == '__main__':
    main()
