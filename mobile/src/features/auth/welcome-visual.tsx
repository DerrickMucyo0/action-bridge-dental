import { StyleSheet, View } from 'react-native';

/** Original, static bridge illustration made entirely from native view geometry. */
export function WelcomeVisual() {
  return (
    <View
      aria-hidden
      accessible={false}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      pointerEvents="none"
      style={styles.canvas}
    >
      <View style={styles.glow} />
      <View style={styles.scene}>
        <View style={[styles.halo, styles.haloOuter]} />
        <View style={[styles.halo, styles.haloInner]} />
        <View style={styles.bridgeEcho} />
        <View style={styles.bridge} />
        <View style={styles.lightHalo} />
        <View style={styles.light} />
        <View style={styles.baseline} />
        <View style={[styles.endpoint, styles.endpointLeft]} />
        <View style={[styles.endpoint, styles.endpointRight]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  canvas: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    backgroundColor: '#071B13',
  },
  glow: {
    position: 'absolute',
    width: 460,
    height: 460,
    borderRadius: 230,
    backgroundColor: '#0D3022',
  },
  scene: {
    width: '82%',
    maxWidth: 340,
    aspectRatio: 4 / 3,
  },
  halo: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: 'rgba(140, 235, 183, 0.12)',
    borderRadius: 999,
  },
  haloOuter: { width: '124%', height: '124%', left: '-12%', top: '-12%' },
  haloInner: { width: '100%', height: '100%', left: 0, top: 0 },
  bridgeEcho: {
    position: 'absolute',
    left: '9%',
    top: '17%',
    width: '82%',
    height: '66%',
    borderWidth: 1,
    borderBottomWidth: 0,
    borderTopLeftRadius: 999,
    borderTopRightRadius: 999,
    borderColor: 'rgba(140, 235, 183, 0.32)',
  },
  bridge: {
    position: 'absolute',
    left: '17%',
    top: '27%',
    width: '66%',
    height: '56%',
    borderWidth: 12,
    borderBottomWidth: 0,
    borderTopLeftRadius: 999,
    borderTopRightRadius: 999,
    borderColor: '#8CEBB7',
  },
  lightHalo: {
    position: 'absolute',
    width: '25%',
    aspectRatio: 1,
    left: '37.5%',
    top: '40%',
    borderRadius: 999,
    backgroundColor: 'rgba(49, 233, 129, 0.08)',
  },
  light: {
    position: 'absolute',
    width: '12%',
    aspectRatio: 1,
    left: '44%',
    top: '49%',
    borderRadius: 999,
    backgroundColor: '#DDFBE9',
  },
  baseline: {
    position: 'absolute',
    left: '3%',
    right: '3%',
    top: '83%',
    height: 1,
    backgroundColor: 'rgba(140, 235, 183, 0.32)',
  },
  endpoint: {
    position: 'absolute',
    width: 8,
    height: 8,
    top: '83%',
    marginTop: -4,
    borderRadius: 4,
    backgroundColor: '#31E981',
  },
  endpointLeft: { left: '3%' },
  endpointRight: { right: '3%' },
});
