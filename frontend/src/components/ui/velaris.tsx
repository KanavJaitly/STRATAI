import { useEffect, useRef, type ReactNode } from 'react'

// Velaris: an animated simplex-noise gradient drawn with WebGL, behind optional children. Adapted from the shadcn
// component to this app's plain CSS (no Tailwind, no cn helper); its classes live in styles/theme.css.
// Decoration only: the canvas is aria-hidden, honours prefers-reduced-motion (one still frame), and when WebGL is
// unavailable (old browsers, jsdom in tests) nothing is drawn and the container's CSS background shows instead.

const VERTEX_SHADER = `
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = position * 0.5 + 0.5;
  gl_Position = vec4(position, 0.0, 1.0);
}
`

const FRAGMENT_SHADER = `
precision highp float;
varying vec2 vUv;

uniform vec2  u_resolution;
uniform float u_time;
uniform float u_grain;
uniform vec3  u_colors[4];
uniform vec3  u_bg;

vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }

float snoise(vec2 v){
  const vec4 C = vec4(0.211324865405187, 0.366025403784439,
           -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy) );
  vec2 x0 = v -   i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute( permute( i.y + vec3(0.0, i1.y, 1.0 ))
  + i.x + vec3(0.0, i1.x, 1.0 ));
  vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy),
    dot(x12.zw,x12.zw)), 0.0);
  m = m*m ;
  m = m*m ;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * ( a0*a0 + h*h );
  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = vUv;
  float ratio = u_resolution.x / u_resolution.y;
  vec2 p = uv - 0.5;
  p.x *= ratio;

  float t = u_time * 0.1;

  float n1 = snoise(p * 0.4 + vec2(t * 0.2, -t * 0.3));
  float n2 = snoise(p * 0.55 + vec2(-t * 0.15, t * 0.25) + n1 * 0.25);
  float n3 = snoise(p * 0.75 + vec2(t * 0.1, -t * 0.2) + n2 * 0.2);

  vec3 col = u_bg;

  float dist = length(p) * 1.5;
  float vignette = 1.0 - smoothstep(0.3, 1.2, dist);

  col = mix(col, u_colors[0], smoothstep(-0.2, 0.5, n1) * 0.85);
  col = mix(col, u_colors[1], smoothstep(-0.1, 0.6, n2) * 0.7);
  col = mix(col, u_colors[2], smoothstep(-0.3, 0.4, n3) * 0.6);
  col = mix(col, u_colors[3], smoothstep(0.0, 0.7, n1 * n2) * 0.5);

  float glow = smoothstep(0.8, 0.0, dist) * 0.3;
  col += u_colors[1] * glow;

  col = mix(col * 0.2, col, vignette);

  float grain = fract(sin(dot(uv, vec2(12.9898, 78.233))) * 43758.5453 + u_time);
  col += (grain - 0.5) * u_grain * 0.1;

  gl_FragColor = vec4(col, 1.0);
}
`

export interface VelarisProps {
  bg?: string
  colors?: string[]
  speed?: number
  grain?: number
  /** A CSS height; omit it to let the content (or the stylesheet) size the container. */
  height?: string
  className?: string
  children?: ReactNode
}

const DEFAULT_COLORS = ['#86efac', '#4ade80', '#059669', '#000000']

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255]
}

export default function Velaris({
  bg = '#000000', colors = DEFAULT_COLORS, speed = 2.0, grain = 0.3, height, className, children,
}: VelarisProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  // A caller passing a new array literal each render must not restart the WebGL program, so the effect keys on the
  // colours' text, not the array's identity.
  const colorKey = colors.slice(0, 4).join(',')

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container || typeof WebGLRenderingContext === 'undefined') return
    const gl = canvas.getContext('webgl')
    if (!gl) return

    const shaders: WebGLShader[] = []
    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type)!
      gl.shaderSource(shader, source)
      gl.compileShader(shader)
      shaders.push(shader)
      return shader
    }
    const program = gl.createProgram()!
    gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX_SHADER))
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT_SHADER))
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return
    gl.useProgram(program)

    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const position = gl.getAttribLocation(program, 'position')
    gl.enableVertexAttribArray(position)
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)

    const locations = {
      res: gl.getUniformLocation(program, 'u_resolution'),
      time: gl.getUniformLocation(program, 'u_time'),
      grain: gl.getUniformLocation(program, 'u_grain'),
      colors: gl.getUniformLocation(program, 'u_colors'),
      bg: gl.getUniformLocation(program, 'u_bg'),
    }
    // Uniforms that do not change between frames are set once.
    gl.uniform1f(locations.grain, grain)
    gl.uniform3f(locations.bg, ...hexToRgb(bg))
    gl.uniform3fv(locations.colors, new Float32Array(colorKey.split(',').flatMap(hexToRgb)))

    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    let raf = 0
    const draw = (t: number) => {
      gl.uniform2f(locations.res, canvas.width, canvas.height)
      gl.uniform1f(locations.time, t * 0.001 * speed)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    }
    const loop = (t: number) => { draw(t); raf = requestAnimationFrame(loop) }

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.round(container.clientWidth * dpr))
      canvas.height = Math.max(1, Math.round(container.clientHeight * dpr))
      gl.viewport(0, 0, canvas.width, canvas.height)
      if (reducedMotion) draw(8000) // a still frame, redrawn at the new size
    }
    const observer = new ResizeObserver(resize)
    observer.observe(container)
    resize()
    if (!reducedMotion) raf = requestAnimationFrame(loop)

    return () => {
      observer.disconnect()
      cancelAnimationFrame(raf)
      gl.deleteBuffer(buffer)
      for (const shader of shaders) gl.deleteShader(shader)
      gl.deleteProgram(program)
    }
  }, [bg, colorKey, speed, grain])

  return (
    <div ref={containerRef} style={height ? { height } : undefined}
      className={['velaris', className].filter(Boolean).join(' ')}>
      <canvas ref={canvasRef} className="velaris-canvas" aria-hidden="true" />
      {children !== undefined && <div className="velaris-content">{children}</div>}
    </div>
  )
}
