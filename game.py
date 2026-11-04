import asyncio
import json
import math
import random

from js import Object, THREE, document, window
from pyodide.ffi import create_proxy, to_js
from pyodide.http import pyfetch


def js_obj(**kw):
    """Convierte argumentos de Python en un objeto JavaScript."""
    return to_js(kw, dict_converter=Object.fromEntries)


def lambert(color, **kw):
    return THREE.MeshStandardMaterial.new(js_obj(color=color, **kw))


def by_id(name):
    return document.getElementById(name)


class Player:
    """Jugador: carril, salto (física) y animación."""
    LANE_WIDTH = 2.5

    def __init__(self, scene):
        self.scene = scene
        self.current_lane = 0          # -1 izquierda, 0 centro, 1 derecha
        self.target_x = 0.0
        self.pos_y = 0.6
        self.is_jumping = False
        self.jump_velocity = 0.0
        self.gravity = -0.015
        self.anim_time = 0.0

        self.group = THREE.Group.new()
        self.body = self._part(0.8, 1.0, 0.5, 0x4f46e5, (0, 0.5, 0))
        self._part(0.5, 0.5, 0.5, 0xf87171, (0, 1.3, 0))                      # cabeza
        self.left_leg = self._part(0.3, 0.6, 0.3, 0x1e293b, (-0.25, -0.1, 0))
        self.right_leg = self._part(0.3, 0.6, 0.3, 0x1e293b, (0.25, -0.1, 0))
        self.group.position.set(0, self.pos_y, 0)
        scene.add(self.group)

    def _part(self, w, h, d, color, pos):
        mesh = THREE.Mesh.new(THREE.BoxGeometry.new(w, h, d), lambert(color, roughness=0.3))
        mesh.position.set(*pos)
        mesh.castShadow = True
        self.group.add(mesh)
        return mesh

    def move_left(self):
        if self.current_lane > -1:
            self.current_lane -= 1
            self.target_x = self.current_lane * self.LANE_WIDTH

    def move_right(self):
        if self.current_lane < 1:
            self.current_lane += 1
            self.target_x = self.current_lane * self.LANE_WIDTH

    def jump(self):
        if not self.is_jumping:
            self.is_jumping = True
            self.jump_velocity = 0.28

    def update(self):
        self.group.position.x += (self.target_x - self.group.position.x) * 0.2
        self.group.rotation.z = (self.group.position.x - self.target_x) * 0.1

        if self.is_jumping:
            self.pos_y += self.jump_velocity
            self.jump_velocity += self.gravity
            if self.pos_y <= 0.6:
                self.pos_y = 0.6
                self.is_jumping = False
                self.jump_velocity = 0.0
        self.group.position.y = self.pos_y

        if not self.is_jumping:
            self.anim_time += 0.25
            self.left_leg.rotation.x = math.sin(self.anim_time) * 0.6
            self.right_leg.rotation.x = -math.sin(self.anim_time) * 0.6
        else:
            self.left_leg.rotation.x = -0.5
            self.right_leg.rotation.x = 0.5

    def reset(self):
        self.current_lane = 0
        self.target_x = 0.0
        self.pos_y = 0.6
        self.is_jumping = False
        self.jump_velocity = 0.0
        self.group.position.set(0, 0.6, 0)


class TrackGrid:
    """Pista infinita hecha de segmentos que se reciclan."""
    SEGMENT_LENGTH = 20
    NUM_SEGMENTS = 6

    def __init__(self, scene):
        self.scene = scene
        self.segments = []
        for i in range(self.NUM_SEGMENTS):
            self._create_segment(-i * self.SEGMENT_LENGTH)

    def _create_segment(self, z):
        L = self.SEGMENT_LENGTH
        group = THREE.Group.new()

        floor = THREE.Mesh.new(THREE.PlaneGeometry.new(10, L), lambert(0x1e293b, roughness=0.8))
        floor.rotation.x = -math.pi / 2
        floor.receiveShadow = True
        group.add(floor)

        line_mat = THREE.MeshBasicMaterial.new(js_obj(color=0x334155))
        for x in (-1.25, 1.25):
            line = THREE.Mesh.new(THREE.PlaneGeometry.new(0.1, L), line_mat)
            line.rotation.x = -math.pi / 2
            line.position.set(x, 0.01, 0)
            group.add(line)

        for x in (-5, 5):
            wall = THREE.Mesh.new(THREE.BoxGeometry.new(0.5, 2, L), lambert(0x0f172a))
            wall.position.set(x, 1, 0)
            group.add(wall)

        group.position.z = z
        self.scene.add(group)
        self.segments.append(group)

    def update(self, speed):
        for seg in self.segments:
            seg.position.z += speed
        if self.segments[0].position.z > self.SEGMENT_LENGTH:
            first = self.segments.pop(0)
            first.position.z = self.segments[-1].position.z - self.SEGMENT_LENGTH
            self.segments.append(first)


class ObjectPool:
    """Obstáculos y monedas: generación, movimiento y colisiones (Box3)."""
    LANE_WIDTH = 2.5

    def __init__(self, scene):
        self.scene = scene
        self.obstacles = []
        self.coins = []
        self.spawn_timer = 0

    def spawn(self, speed):
        self.spawn_timer += 1
        if self.spawn_timer > max(30, 70 - int(speed * 30)):
            self.spawn_timer = 0
            lane = random.randint(-1, 1)
            if random.random() > 0.4:
                self._create_obstacle(lane)
            else:
                self._create_coins(lane)

    def _create_obstacle(self, lane):
        tall = random.random() > 0.5
        height = 1.8 if tall else 1.0
        mat = lambert(0xef4444 if tall else 0xf97316, roughness=0.4)
        mesh = THREE.Mesh.new(THREE.BoxGeometry.new(2, height, 1), mat)
        mesh.position.set(lane * self.LANE_WIDTH, height / 2, -60)
        mesh.castShadow = True
        self.scene.add(mesh)
        self.obstacles.append({"mesh": mesh, "bounds": THREE.Box3.new()})

    def _create_coins(self, lane):
        for i in range(3):
            coin = THREE.Mesh.new(THREE.CylinderGeometry.new(0.4, 0.4, 0.1, 16),
                                  lambert(0xfacc15, metalness=0.8, roughness=0.2))
            coin.rotation.x = math.pi / 2
            coin.position.set(lane * self.LANE_WIDTH, 0.8, -60 - i * 2.5)
            coin.castShadow = True
            self.scene.add(coin)
            self.coins.append(coin)

    def update(self, speed, player, on_coin, on_hit):
        player_box = THREE.Box3.new().setFromObject(player.group)

        for obs in self.obstacles[:]:
            obs["mesh"].position.z += speed
            obs["bounds"].setFromObject(obs["mesh"])
            if player_box.intersectsBox(obs["bounds"]):
                on_hit()
                return
            if obs["mesh"].position.z > 10:
                self.scene.remove(obs["mesh"])
                self.obstacles.remove(obs)

        for coin in self.coins[:]:
            coin.position.z += speed
            coin.rotation.z += 0.05
            if player_box.intersectsBox(THREE.Box3.new().setFromObject(coin)):
                self.scene.remove(coin)
                self.coins.remove(coin)
                on_coin()
            elif coin.position.z > 10:
                self.scene.remove(coin)
                self.coins.remove(coin)

    def clear(self):
        for obs in self.obstacles:
            self.scene.remove(obs["mesh"])
        for coin in self.coins:
            self.scene.remove(coin)
        self.obstacles, self.coins = [], []


class GameEngine:
    """Escena 3D, bucle principal, entradas y estado del juego."""

    def __init__(self):
        self.playing = False
        self.score = 0.0
        self.coins = 0
        self.speed = 0.4
        self._init_three()
        self.player = Player(self.scene)
        self.track = TrackGrid(self.scene)
        self.pool = ObjectPool(self.scene)
        self._bind_events()

        self._loop_proxy = create_proxy(self._animate)
        window.requestAnimationFrame(self._loop_proxy)

        btn = by_id("btn-start")
        btn.disabled = False
        btn.innerText = "¡EMPEZAR A CORRER!"

    def _init_three(self):
        self.scene = THREE.Scene.new()
        self.scene.background = THREE.Color.new(0x0f172a)
        self.scene.fog = THREE.Fog.new(0x0f172a, 20, 70)

        self.camera = THREE.PerspectiveCamera.new(60, window.innerWidth / window.innerHeight, 0.1, 100)
        self.camera.position.set(0, 4, 7)
        self.camera.lookAt(0, 1, -2)

        self.renderer = THREE.WebGLRenderer.new(js_obj(canvas=by_id("game-canvas"), antialias=True))
        self.renderer.setSize(window.innerWidth, window.innerHeight)
        self.renderer.setPixelRatio(min(window.devicePixelRatio, 2))
        self.renderer.shadowMap.enabled = True

        self.scene.add(THREE.AmbientLight.new(0xffffff, 0.6))
        sun = THREE.DirectionalLight.new(0xffffff, 0.8)
        sun.position.set(10, 20, 10)
        sun.castShadow = True
        self.scene.add(sun)

    def _bind_events(self):
        self._proxies = []  # evita que Python libere los callbacks

        def on(target, name, fn):
            p = create_proxy(fn)
            self._proxies.append(p)
            target.addEventListener(name, p)

        def on_key(e):
            if not self.playing:
                return
            if e.key in ("ArrowLeft", "a", "A"):
                self.player.move_left()
            elif e.key in ("ArrowRight", "d", "D"):
                self.player.move_right()
            elif e.key in ("ArrowUp", " ", "w", "W"):
                self.player.jump()

        touch = {"x": 0, "y": 0}

        def on_touch_start(e):
            touch["x"], touch["y"] = e.touches[0].clientX, e.touches[0].clientY

        def on_touch_end(e):
            if not self.playing:
                return
            dx = e.changedTouches[0].clientX - touch["x"]
            dy = e.changedTouches[0].clientY - touch["y"]
            if abs(dx) > abs(dy):
                if dx > 30:
                    self.player.move_right()
                elif dx < -30:
                    self.player.move_left()
            elif dy < -30:
                self.player.jump()

        def on_resize(e):
            self.camera.aspect = window.innerWidth / window.innerHeight
            self.camera.updateProjectionMatrix()
            self.renderer.setSize(window.innerWidth, window.innerHeight)

        on(window, "keydown", on_key)
        on(window, "touchstart", on_touch_start)
        on(window, "touchend", on_touch_end)
        on(window, "resize", on_resize)
        on(by_id("btn-start"), "click", lambda e: self.start())
        on(by_id("btn-restart"), "click", lambda e: self.start())

    def start(self):
        by_id("screen-start").classList.add("hidden")
        by_id("screen-gameover").classList.add("hidden")
        self.playing = True
        self.score, self.coins, self.speed = 0.0, 0, 0.4
        by_id("coins-display").innerText = "0"
        self.player.reset()
        self.pool.clear()

    def game_over(self):
        self.playing = False
        by_id("final-score").innerText = f"{int(self.score)}m"
        by_id("final-coins").innerText = str(self.coins)
        by_id("screen-gameover").classList.remove("hidden")
        asyncio.ensure_future(self._submit_score())

    async def _submit_score(self):
        """Guarda y muestra el ranking local usando localStorage del navegador."""
        board = by_id("board")
        try:
            raw_data = window.localStorage.getItem("game_leaderboard")
            top = json.loads(str(raw_data)) if raw_data else []
            
            top.append({"name": "Runner", "score": int(self.score)})
            top = sorted(top, key=lambda x: x["score"], reverse=True)[:5]
            
            window.localStorage.setItem("game_leaderboard", json.dumps(top))
            
            board.innerHTML = ""
            for entry in top:
                li = document.createElement("li")
                li.textContent = f"{entry['name']} — {entry['score']}m"
                board.appendChild(li)
        except Exception:
            board.textContent = "Ranking local no disponible"

    def _on_coin(self):
        self.coins += 1
        by_id("coins-display").innerText = str(self.coins)

    def _animate(self, *_):
        if self.playing:
            self.score += 0.2
            self.speed += 0.0001
            self.player.update()
            self.track.update(self.speed)
            self.pool.spawn(self.speed)
            self.pool.update(self.speed, self.player, self._on_coin, self.game_over)
            by_id("score-display").innerText = f"{int(self.score)}m"
        self.renderer.render(self.scene, self.camera)
        window.requestAnimationFrame(self._loop_proxy)

engine = GameEngine()